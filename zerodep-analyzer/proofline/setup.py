from setuptools import setup, find_packages

setup(
    name="proofline",
    version="6.0.0",
    description="The Zero-Dependency Package Killer: AI Verification Engine",
    author="Zero Dependency Hackathon",
    packages=find_packages(include=["proofline", "proofline.*"]),
    entry_points={
        "console_scripts": [
            "proofline=proofline.cli:main",
        ],
    },
    python_requires=">=3.8",
)
