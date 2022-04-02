import setuptools

with open("README.md","r") as fh:
    long_description = fh.read()

setuptools.setup(name="PyBMP",version="0.2",author="Danie Britto",author_email="dannybritto96@gmail.com",packages=setuptools.find_packages(),description = "Python package to read a BMP file's header and pixel array in binary.",long_description = long_description,long_description_content_type="text/markdown",url="https://github.com/dannybritto96/pybmp",classifiers = ["Programming Language :: Python :: 3","License :: OSI Approved :: MIT License","Operating System :: OS Independent"],)
