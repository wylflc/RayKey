import unittest
from common import EXP, PRIOR, sw, read
from analyze_eval import validate_nav, old, same_direction, platform


class IntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.row=next(r for r in read(PRIOR/'summary_rows.csv') if r['group']=='full' and r['arm']=='BASE' and r['start']=='2011-11-01')
        cls.daily=read(PRIOR/'nav'/f"{cls.row['nav_tag']}.csv")
        cls.dates=tuple(r['date'] for r in cls.daily)

    def test_complete_path_passes(self):
        validate_nav(self.row,self.daily,self.dates)

    def test_equal_missing_window_is_rejected(self):
        r=dict(self.row)
        r[sw.WIN5_KEY]=';'.join(r[sw.WIN5_KEY].split(';')[1:])
        with self.assertRaisesRegex(AssertionError,'calendar window'):validate_nav(r,self.daily,self.dates)

    def test_daily_gap_is_rejected(self):
        with self.assertRaises(AssertionError):validate_nav(self.row,self.daily[1:],self.dates)

    def test_noise_does_not_hide_material_sign_reversal(self):
        self.assertFalse(same_direction([-.5,2.,3.,.2],.15))
        self.assertTrue(same_direction([-.04,2.,3.,.2],.15))
        self.assertFalse(same_direction([-.04,2.,3.,.2]))

    def test_platform_must_contain_center_and_be_contiguous(self):
        self.assertEqual(platform([10,11,12,13,14],[True,True,False,True,True],12),[])
        self.assertEqual(platform([10,11,12,13,14],[False,True,True,True,False],12),[11,12,13])


if __name__=='__main__':unittest.main()
