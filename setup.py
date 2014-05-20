import os
from setuptools import setup

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name = "rdoclient",
    version = "1.0.0",
    author = "RANDOM.ORG",
    author_email = "contact@random.org",
    description = ("RANDOM.ORG JSON-RPC API (Revision 1) implementation."),
    license = "MIT",
    keywords = "RANDOM.ORG random client implementation",
    url = "http://packages.python.org/rdoclient",
    packages=['rdoclient'],
    long_description=read('README.rst'),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 2.7",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)