# Py BMP

Python package to read a BMP file's header and pixel array in binary.

## Install Instructions

```shell
pip install pybmp-dannybritto96
```

## Usage

```python
from pybmp import BMP

img = BMP(filename="sample.bmp")

print(img.SHAPE)
print(img.PIXELARRAY)
print(img.RAWIMGSIZE)
```

Refer: <https://en.wikipedia.org/wiki/BMP_file_format>