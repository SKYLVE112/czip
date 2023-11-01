# for developer

```shell
cd docs
rm -rf build
ln -s ~/Projects/Github/czip/notebooks/ source/notebooks
sphinx-apidoc -e -o source -f ../../czip
make html
rm -rf source/notebooks
cd ..
ls
```

```shell
rm -rf dist && rm -rf czip.egg-info/
python setup.py sdist bdist_wheel
twine upload dist/*
```