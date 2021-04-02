import os
from setuptools import setup

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name = "rdoclient",
    version = "1.4",
    author = "RANDOM.ORG",
    author_email = "contact@random.org",
    description = ("RANDOM.ORG JSON-RPC API (Release 4) implementation."),
    license = "MIT",
    keywords = "RANDOM.ORG random client implementation",
    url = "https://www.random.org/",
    packages=['rdoclient'],
    long_description=read('README.rst'),
    install_requires=[
        'requests',
        'six',
    ],
    project_urls={
        "Documentation": "https://api.random.org/json-rpc/4",
        "Source Code": "https://github.com/RandomOrg/JSON-RPC-Python",
    },
    python_requires=">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
