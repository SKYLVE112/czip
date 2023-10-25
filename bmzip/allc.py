#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Created on Tue Sep  8 17:34:38 2020

@author: DingWB
"""
import itertools
import sys
import os
import struct
import pandas as pd
import pysam
import multiprocessing
from Bio import SeqIO
import numpy as np
from collections import defaultdict
import random
from .utils import WriteC
from .bmz import Reader, Writer, get_dtfuncs
import numba
# ==========================================================
class AllC:
    def __init__(self, Genome=None, Output="hg38_allc.mz",
                 pattern="C", n_jobs=12):
        """
        Extract position of specific pattern in the reference genome, for example C.
            Example: python ~/Scripts/python/tbmate.py AllC -g ~/genome/hg38/hg38.fa --n_jobs 10 run
            Or call within python: ac=AllC(genome="/gale/netapp/home2/wding/genome/hg38/hg38.fa")
        Parameters
        ----------
        genome: path
            reference genome.
        out: path
            path for output
        pattern: str
            pattern [C]
        n_jobs: int
            number of CPU used for Pool.
        """
        self.genome=os.path.abspath(os.path.expanduser(Genome))
        self.Output=os.path.abspath(os.path.expanduser(Output))
        self.outdir=self.Output+'.tmp'
        if not os.path.exists(self.outdir):
            os.mkdir(self.outdir)
        self.pattern=pattern
        self.records = SeqIO.parse(self.genome, "fasta")
        self.n_jobs = n_jobs if not n_jobs is None else os.cpu_count()
        if pattern=='C':
            self.func=WriteC

    def writePattern(self):
        pool = multiprocessing.Pool(self.n_jobs)
        jobs = []
        for record in self.records:
            job = pool.apply_async(self.func, (record,self.outdir))
            jobs.append(job)
        for job in jobs:
            job.get()
        pool.close()
        pool.join()

    def merge(self):
        writer = Writer(Output=self.Output, Formats=['Q', 'c', '3s'],
                        Columns=['pos', 'strand', 'context'],
                        Dimensions=['chrom'], message=self.genome)
        writer.catmz(Input=f"{self.outdir}/*.mz")

    def run(self):
        self.writePattern()
        self.merge()
        os.system(f"rm -rf {self.outdir}")

def allc2mz(allc_path, outfile, reference=None, missing_value=[0, 0],
            pr=0, pa=1, sep='\t', Path_to_chrom=None, chunksize=2000):
    """
    convert allc.tsv.gz to .mz file.

    Parameters
    ----------
    allc_path : path
        path to allc.tsv.gz, should has .tbi index.
    outfile : path
        output .mz file
    reference : path
        path to reference coordinates.
    chunksize : int
        default is 5000
    Path_to_chrom : path
        path to chrom_size path or similar file containing chromosomes order,
        the first columns should be chromosomes, tab separated and no header.

    Returns
    -------

    """
    if os.path.exists(outfile):
        print(f"{outfile} existed, skip.")
        return
    allc_path = os.path.abspath(os.path.expanduser(allc_path))
    if not os.path.exists(allc_path + '.tbi'):
        raise ValueError(f"index file .tbi not existed, please create index first.")
    print(allc_path)
    tbi = pysam.TabixFile(allc_path)
    contigs = tbi.contigs
    if not Path_to_chrom is None:
        Path_to_chrom = os.path.abspath(os.path.expanduser(Path_to_chrom))
        df = pd.read_csv(Path_to_chrom, sep='\t', header=None, usecols=[0])
        chroms = df.iloc[:, 0].tolist()
        all_chroms = [c for c in chroms if c in contigs]
    else:
        all_chroms = contigs
    if not reference is None:
        reference = os.path.abspath(os.path.expanduser(reference))
        message = os.path.basename(reference)
        formats, columns, dimensions = ['H', 'H'], ['mc', 'cov'], ['chrom']
        usecols = [4, 5]
    else:
        message = ''
        formats, columns, dimensions = ['Q', 'H', 'H'], ['pos', 'mc', 'cov'], ['chrom']
        usecols = [1, 4, 5]
    writer = Writer(outfile, Formats=formats, Columns=columns,
                    Dimensions=dimensions, message=message)
    dtfuncs = get_dtfuncs(formats, tobytes=False)

    if not reference is None:
        ref_reader = Reader(reference)
        na_value_bytes = struct.pack(f"<{writer.fmts}", *missing_value)
        for chrom in all_chroms:
            # print(chrom,'\t'*4,end='\r')
            # method 1
            ref_positions = ref_reader.__fetch__(tuple([chrom]), s=pr, e=pr + 1)
            data, i = b'', 0
            for line in tbi.fetch(chrom):
                row_query = line.rstrip('\n').split(sep)
                row_query_pos = int(row_query[pa])
                for ref_pos in ref_positions:
                    if ref_pos[0] < row_query_pos:
                        data += na_value_bytes
                        i += 1
                        if i > chunksize:
                            writer.write_chunk(data, [chrom])
                            data, i = b'', 0
                    elif ref_pos[0] == row_query_pos:
                        data += struct.pack(f"<{writer.fmts}",
                                            *[func(row_query[i]) for i, func in
                                              zip(usecols, dtfuncs)
                                              ])
                        i += 1
                        break
                    else:
                        break
                if i > chunksize:
                    writer.write_chunk(data, [chrom])
                    data, i = b'', 0
            if len(data) > 0:
                writer.write_chunk(data, [chrom])

            # methd 2, similar speed, but larger memory requirement.
            # ref_positions = np.array([pos[0] for pos in ref_reader.__fetch__(tuple([chrom]), s=pr, e=pr + 1)])
            # records = [line.rstrip('\n').split(sep) for line in tbi.fetch(chrom)]
            # query_positions = np.array([int(record[pa]) for record in records])
            # indices = np.where(np.in1d(ref_positions, query_positions))[0]
            # # indices is the indice where element of query_positions in ref_positions
            # indice_start = 0
            # # sum=0
            # for indice, record in zip(indices, records):
            #     for i in range((indice - indice_start) // chunksize):
            #         writer.write_chunk(na_value_bytes * chunksize, [chrom])
            #         # sum+=chunksize
            #     i = (indice - indice_start) % chunksize
            #     data = b''
            #     if i > 0:
            #         data += na_value_bytes * i
            #         # sum += i
            #     data += struct.pack(f"<{writer.fmts}", *[func(record[i]) for i, func in
            #                                              zip(usecols, dtfuncs)])
            #     writer.write_chunk(data, [chrom])
            #     # sum += 1
            #     indice_start = indice + 1
            # indice = len(ref_positions)
            # for i in range((indice - indice_start) // chunksize):
            #     writer.write_chunk(na_value_bytes * chunksize, [chrom])
            #     # sum += chunksize
            # i = (indice - indice_start) % chunksize
            # if i > 0:
            #     writer.write_chunk(na_value_bytes * i, [chrom])
            #     # sum += i
        ref_reader.close()
    else:
        for chrom in all_chroms:
            # print(chrom)
            # records = tbi.fetch(chrom)
            # data, i = b'', 0
            # while True:
            #     try:
            #         values = records.__next__().rstrip('\n').split(sep)
            #     except:
            #         break
            #     if i >= chunksize:  # dims are the same, but reach chunksize
            #         writer.write_chunk(data, [chrom])
            #         data, i = b'', 0
            #     values = [func(values[i]) for i, func in zip(usecols, dtfuncs)]
            #     data += struct.pack(f"<{writer.fmts}", *values)
            #     i += 1
            # if len(data) > 0:
            #     writer.write_chunk(data, [chrom])

            # method 2
            for line in tbi.fetch(chrom):
                values = line.rstrip('\n').split(sep)
                data = struct.pack(f"<{writer.fmts}",
                                   *[func(values[i]) for i, func in zip(usecols, dtfuncs)])
                writer.write_chunk(data, [chrom])
    writer.close()
    tbi.close()
# ==========================================================
def _isCG(context):
    return context[:2] == b'CG'


# ==========================================================
def _isCH(context):
    return not _isCG(context)


# ==========================================================
def generate_context_ssi(Input, output=None, pattern='CGN'):
    if pattern == 'CGN':
        judge_func = _isCG
    else:  # CH
        judge_func = _isCH
    if output is None:
        output = Input + '.' + pattern + '.bmi'
    else:
        output = os.path.abspath(os.path.expanduser(output))
    reader = Reader(Input)
    reader.category_ssi(output=output, formats=['I'], columns=['ID'],
                        dimensions=['chrom'], col=2, match_func=judge_func,
                        chunksize=2000)
    reader.close()


def prepare_sky(smk=None, sky=None, indir=None, outdir=None, allc_path=None,
                reference=None, ref_prefix=None, chrom=None, chrom_prefix=None,
                gcp=False, bucket=None, cpu=24, name=None):
    if smk is None:
        smk = os.path.join(os.path.dirname(__file__),
                           "data/snakemake_template/run_allc2mz.smk")
    if sky is None:
        sky = os.path.join(os.path.dirname(__file__),
                           "data/skypilot_template/run_allc2mz.yaml")
    if name is None:
        name = 'allc2mz'
    workdir = os.path.basename("./")
    D = {
        'indir': indir, 'outdir': outdir, 'allc_path': allc_path,
        'reference': reference, 'ref_prefix': ref_prefix, 'chrom': chrom,
        'chrom_prefix': chrom_prefix, 'gcp': gcp, 'bucket': bucket,
        'cpu': cpu
    }
    for k in D:
        if D[k] is None:
            D[k] = ''
        else:
            if k not in ['bucket', 'cpu']:
                value = D[k]
                D[k] = f"{k}={value}"
    # D['smk']=smk
    D['name'] = name
    D['workdir'] = workdir
    with open(sky, 'r') as f:
        template = f.read()
    # with open(out_yaml,'w') as f:
    #     f.write(template.format(**D))
    print(template.format(**D))
    print("# sky launch -c test 1.yaml")
    print("# sky spot launch -y -n job job.yaml")

def copy_smk(outname=None):
    if outname is None:
        outname = os.path.abspath("job.yaml")
    smk = os.path.join(os.path.dirname(__file__),
                       "data/snakemake_template/run_allc2mz.smk")
    os.system(f"cp {smk} {outname}")
# ==========================================================
if __name__ == "__main__":
    import fire

    fire.core.Display = lambda lines, out: print(*lines, file=out)
    fire.Fire()
