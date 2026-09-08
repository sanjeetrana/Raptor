import unittest
import tempfile
import os
import shutil
from proofline.deps_auditor import check_dependencies

class TestDepsAuditor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.before_dir = os.path.join(self.temp_dir.name, 'v1')
        self.after_dir = os.path.join(self.temp_dir.name, 'v2')
        os.makedirs(self.before_dir)
        os.makedirs(self.after_dir)

    def tearDown(self):
        self.temp_dir.cleanup()
        
    def test_no_requirements_file(self):
        rules = check_dependencies(self.before_dir, self.after_dir)
        self.assertEqual(len(rules), 0)

    def test_no_new_dependencies(self):
        with open(os.path.join(self.before_dir, "requirements.txt"), "w") as f:
            f.write("requests==2.28.1\n")
        with open(os.path.join(self.after_dir, "requirements.txt"), "w") as f:
            f.write("requests==2.29.0\n")
            
        rules = check_dependencies(self.before_dir, self.after_dir)
        self.assertEqual(len(rules), 0)

    def test_new_dependency_added(self):
        with open(os.path.join(self.before_dir, "requirements.txt"), "w") as f:
            f.write("requests==2.28.1\n")
        with open(os.path.join(self.after_dir, "requirements.txt"), "w") as f:
            f.write("requests==2.29.0\nflask>=2.0\n")
            
        rules = check_dependencies(self.before_dir, self.after_dir)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].rule_id, 10)
        self.assertEqual(rules[0].rule_name, "Dependency Attack Surface Increased")
        self.assertIn("flask", rules[0].evidence)

    def test_comments_ignored(self):
        with open(os.path.join(self.after_dir, "requirements.txt"), "w") as f:
            f.write("# this is a comment\nflask\n")
            
        rules = check_dependencies(self.before_dir, self.after_dir)
        self.assertEqual(len(rules), 1)
        self.assertIn("flask", rules[0].evidence)

if __name__ == '__main__':
    unittest.main()
