import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import Image
import logo_assets
import reference_styles as ref


class ReferenceImageTests(unittest.TestCase):
    url='https://images.example.org/portrait.jpg'

    def response(self,payload):
        response=io.BytesIO(payload);response.headers={'Content-Length':str(len(payload))}
        opener=MagicMock();opener.open.return_value=response
        return patch.object(logo_assets.urllib.request,'build_opener',return_value=opener)

    def test_camera_photo_is_downsized_but_logo_limit_is_unchanged(self):
        data=io.BytesIO()
        with Image.new('RGB',(4800,3600),(100,140,180)) as image: image.save(data,'JPEG')
        with tempfile.TemporaryDirectory() as folder,patch.object(logo_assets,'public_image_url'):
            target=Path(folder)/'photo.png'
            with self.response(data.getvalue()): logo_assets.fetch_reference_image(self.url,target)
            with Image.open(target) as image:
                self.assertEqual(image.size,(2560,1920));self.assertEqual(image.mode,'RGBA')
                self.assertEqual(image.getpixel((1200,900))[3],255)
            with self.response(data.getvalue()),self.assertRaisesRegex(ValueError,'16 megapixels'):
                logo_assets.fetch_logo(self.url,Path(folder)/'logo.png')

    def test_alpha_and_camera_orientation_survive_preparation(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(logo_assets,'public_image_url'):
            target=Path(folder)/'image.png';data=io.BytesIO()
            with Image.new('RGBA',(80,40),(100,140,180,90)) as image: image.save(data,'PNG')
            with self.response(data.getvalue()): logo_assets.fetch_reference_image(self.url,target)
            with Image.open(target) as image: self.assertEqual(image.getpixel((0,0))[3],90)
            data=io.BytesIO()
            with Image.new('RGB',(80,40),'red') as image:
                exif=Image.Exif();exif[274]=6;image.save(data,'JPEG',exif=exif)
            with self.response(data.getvalue()): logo_assets.fetch_reference_image(self.url,target)
            with Image.open(target) as image: self.assertEqual(image.size,(40,80))

    def test_reference_download_keeps_byte_limit_and_rejects_html(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(logo_assets,'public_image_url'):
            target=Path(folder)/'image.png'
            response=io.BytesIO(b'');response.headers={'Content-Length':str(logo_assets.MAX_LOGO_BYTES+1)}
            opener=MagicMock();opener.open.return_value=response
            with patch.object(logo_assets.urllib.request,'build_opener',return_value=opener),self.assertRaisesRegex(ValueError,'12 MB'):
                logo_assets.fetch_reference_image(self.url,target)
            with self.response(b'<html>not an image</html>'),self.assertRaises(OSError):
                logo_assets.fetch_reference_image(self.url,target)
            self.assertFalse(target.exists())

    def test_extreme_pixel_count_is_rejected_before_decoding(self):
        image=MagicMock();image.width=9000;image.height=8000
        image.__enter__.return_value=image
        with tempfile.TemporaryDirectory() as folder,patch.object(logo_assets,'public_image_url'),self.response(b'fake header'),patch('PIL.Image.open',return_value=image):
            with self.assertRaisesRegex(ValueError,'64 megapixels'):
                logo_assets.fetch_reference_image(self.url,Path(folder)/'image.png')
            image.load.assert_not_called()

    def test_asset_failure_names_the_asset_and_removes_pending_file(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(logo_assets,'fetch_reference_image',side_effect=ValueError('Reference image exceeds 12 MB.')):
            with self.assertRaisesRegex(ValueError,'Asset portrait: Reference'):
                ref.prepare_assets(Path(folder),{'assets':[{'id':'portrait','kind':'image','source':self.url}]})
            self.assertEqual(list((Path(folder)/'media/reference').glob('*.pending.png')),[])


if __name__=='__main__': unittest.main()
