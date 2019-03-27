name = 'pybmp'

import sys
import math
import logging
import binascii


class HeaderNotSupported(Exception):
    pass


class BMP:

    logger = logging.getLogger('pybmp')
    logger.setLevel(logging.DEBUG)

    COMPRESSION_DICT = {
        "BI_RGB":0,
        "BI_RLE8":1,
        "BI_RLE4":2,
        "BI_BITFIELDS":3,
        "BI_JPEG":4,
        "BI_PNG":5,
        "BI_ALPHABITFIELDS":6,
        "BI_CMYK":11,
        "BI_CMYKRLE8":12,
        "BI_CMYKRLE4":13
    }

    def PixelArraySize(self,BITSPERPIXEL,IMAGEWIDTH,IMAGEHEIGHT):
        ROWSIZE = math.floor((BITSPERPIXEL*IMAGEWIDTH+31)/32)*4
        PIXELARRAYSIZE = ROWSIZE*abs(IMAGEHEIGHT)
        return PIXELARRAYSIZE

    def unhexlify(self, bytedata):
        return binascii.unhexlify(bytedata)

    def bytes2int(self,bytedata):
        return int.from_bytes(binascii.unhexlify(bytedata),byteorder=sys.byteorder)
    
    def compression_method(self, compression):
        for key, value in self.COMPRESSION_DICT.items():
            if value == compression:
                self.logger.info("Compression Method: %s" % key)
    
    def __init__(self, filename):

        with open(filename,"rb") as f:
            content = f.read()
            content = binascii.hexlify(content)
            self.ID = self.unhexlify(content[:4]).decode('utf-8')
            self.SIZE = self.bytes2int(content[4:12])
            self.RESERVED = self.bytes2int(content[12:20])
            self.OFFSET = self.bytes2int(content[20:28])
            self.DIBHEADER = self.bytes2int(content[28:36])
            
            if self.DIBHEADER == 40:
                self.logger.info("Header Type: BITMAPINFOHEADER")
                self.WIDTH = self.bytes2int(content[36:44])
                self.HEIGHT = self.bytes2int(content[44:52])
                self.NCOLORPANES = self.bytes2int(content[52:56])
                self.NBITSPERPIXEL = self.bytes2int(content[56:60])
                self.COMPRESSION = self.bytes2int(content[60:68])
                self.RAWIMGSIZE = self.bytes2int(content[68:74])
                self.HORIZONTALRES = self.bytes2int(content[74:82])
                self.VERTICALRES = self.bytes2int(content[82:90])
                self.NCOLORS = self.bytes2int(content[90:98])
                self.NIMPCOLORS = self.bytes2int(content[98:106])
                self.PIXELARRAY = self.unhexlify(content[106:106+self.RAWIMGSIZE])
                self.SHAPE = (self.WIDTH,self.HEIGHT)
                self.PIXELARRAYSIZE = self.PixelArraySize(self.NBITSPERPIXEL,self.WIDTH,self.HEIGHT)
                self.compression_method(self.COMPRESSION)

            elif self.DIBHEADER == 12:
                self.logger.info("Header Type: BITMAPCOREHEADER / OS21XBITMAPHEADER")
                self.WIDTH = self.bytes2int(content[36:40])
                self.HEIGHT = self.bytes2int(content[40:44])
                self.NCOLORPANES = self.bytes2int(content[44:48])
                self.NBITSPERPIXEL = self.bytes2int(content[48:52])
                self.SHAPE = (self.WIDTH,self.HEIGHT)
                self.PIXELARRAYSIZE = self.PixelArraySize(self.NBITSPERPIXEL,self.WIDTH,self.HEIGHT)
                self.PIXELARRAY = self.unhexlify(content[52:52+self.PIXELARRAYSIZE])



            elif self.DIBHEADER == 108:
                self.logger.info("Header Type: BITMAPV4HEADER")
                self.WIDTH = self.bytes2int(content[36:44])
                self.HEIGHT = self.bytes2int(content[44:52])
                self.NCOLORPANES = self.bytes2int(content[52:56])
                self.NBITSPERPIXEL = self.bytes2int(content[56:60])
                self.COMPRESSION = self.bytes2int(content[60:68])
                self.RAWIMGSIZE = self.bytes2int(content[68:76])
                self.HORIZONTALRES = self.bytes2int(content[76:84])
                self.VERTICALRES = self.bytes2int(content[84:92])
                self.NCOLORS = self.bytes2int(content[92:100])
                self.NIMPCOLORS = self.bytes2int(content[100:108])
                self.REDMASK = self.unhexlify(content[108:116])
                self.GREENMASK = self.unhexlify(content[116:124])
                self.BLUEMASK = self.unhexlify(content[124:132])
                self.ALPHAMASK = self.unhexlify(content[132:140])
                self.CSTYPE = self.bytes2int(content[140:148])
                self.COLORSPACEENDPOINTS = self.unhexlify(content[148:230]) 
                self.GAMMARED = self.bytes2int(content[230:238])
                self.GAMMAGREEN = self.bytes2int(content[238:246])
                self.GAMMABLUE = self.bytes2int(content[246:252])
                self.PIXELARRAY = self.unhexlify(content[252:252+self.RAWIMGSIZE])
                self.SHAPE = (self.WIDTH,self.HEIGHT)
                self.PIXELARRAYSIZE = self.PixelArraySize(self.NBITSPERPIXEL,self.WIDTH,self.HEIGHT)
                self.compression_method(self.COMPRESSION)

                
            else:
                raise HeaderNotSupported("Header not yet supported")
