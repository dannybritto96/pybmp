import setuptools

with open("README.md","r") as fh:
    long_description = fh.read()

setuptools.setup(name="pybmp",version="0.1",author="Danie Britto",author_email="dannybritto96@gmail.com",packages=setuptools.find_packages(),long_description = long_description,long_description_content_type="text/markdown",url="https://github.com/dannybritto96/pybmp",classifiers = ["Programming Language :: Python :: 3","License :: OSI Approved :: MIT License","Operating System :: OS Independent"],)
