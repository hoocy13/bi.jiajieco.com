import io
import unittest
from unittest.mock import Mock

from PIL import Image
import layout


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.old_model = layout._model
        self.was_ready = layout.ready.is_set()
        self.model = layout._model = Mock()
        layout.ready.set()
        output = io.BytesIO()
        Image.new('RGB',(100,100),'white').save(output,format='PNG')
        self.png = output.getvalue()

    def tearDown(self):
        layout._model = self.old_model
        if not self.was_ready:
            layout.ready.clear()

    def test_detector_order_crop_table_conversion_and_progress(self):
        self.model.predict.return_value = [{'boxes':[
            {'label':'text','score':0.9,'coordinate':[0,50,100,100]},
            {'label':'image','score':0.9,'coordinate':[0,0,50,50]},
            {'label':'table','score':0.9,'coordinate':[0,0,100,50]},
            {'label':'text','score':0.1,'coordinate':[0,0,100,100]},
        ]}]
        sizes = []
        outputs = iter(['lower-first', '<fcel>upper-second<nl>'])
        def infer(png,prompt,tokens):
            with Image.open(io.BytesIO(png)) as image:
                sizes.append(image.size)
            return next(outputs)
        progress = Mock()
        text = layout.recognize(self.png,infer,4096,lambda:False,progress)
        self.assertEqual(sizes,[(100,50),(100,50)])
        self.assertLess(text.index('lower-first'), text.index('upper-second'))
        self.assertIn('<table',text)
        self.assertEqual(progress.call_args_list[0].args,(0,2))
        self.assertEqual(progress.call_args.args,(2,2))

    def test_empty_detection_cancellation_and_unready_model(self):
        self.model.predict.return_value = [{'boxes':[]}]
        with self.assertRaisesRegex(ValueError,'未检测'):
            layout.recognize(self.png,Mock(),4096,lambda:False)
        self.model.predict.return_value = [{'boxes':[{'label':'text','score':0.9,'coordinate':[0,0,100,100]}]}]
        infer = Mock()
        with self.assertRaisesRegex(ValueError,'取消'):
            layout.recognize(self.png,infer,4096,lambda:True)
        infer.assert_not_called()
        layout.ready.clear()
        with self.assertRaisesRegex(ValueError,'尚未就绪'):
            layout.recognize(self.png,infer,4096,lambda:False)


if __name__ == '__main__':
    unittest.main()
