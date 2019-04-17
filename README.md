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

```python
from pybmp import BMP
import binascii
f = open('samp.bmp','rb')
content = f.read()
content = binascii.hexlify(content)
img = BMP(hexdata=hexdata)

print(img.SHAPE)
print(img.PIXELARRAY)
print(img.RAWIMGSIZE)
```

Refer: <https://en.wikipedia.org/wiki/BMP_file_format>