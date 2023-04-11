JSON-RPC-Python
===============

The official RANDOM.ORG JSON-RPC API (Release 4) implementation for Python 2 and 3.

This is a Python implementation of the RANDOM.ORG JSON-RPC API (R4). It provides either serialized or unserialized access to both the signed and unsigned methods of the API through the RandomOrgClient class. It also provides a convenience class through the RandomOrgClient class, the RandomOrgCache, for precaching requests. In the context of this module, a serialized client is one for which the sequence of requests matches the sequence of responses.

Installation
------------

To install, simply:

.. code-block:: bash

    $ pip install rdoclient

Requires the `requests <http://docs.python-requests.org/en/latest/>`_ lib:

.. code-block:: bash

    $ pip install requests

Requires the `six <https://six.readthedocs.io/>`_ lib:

.. code-block:: bash

    $ pip install six


Note that the required dependencies 'requests' and 'six' are installed automatically, when using pip install for 'rdoclient' version >= 1.2.  

Usage
-----

The default setup is best for non-time-critical serialized requests, e.g., batch clients:

.. code-block:: pycon

    >>> from rdoclient import RandomOrgClient
    >>> r = RandomOrgClient(YOUR_API_KEY_HERE)
    >>> r.generate_integers(5, 0, 10)
    [6, 2, 8, 9, 2]

...or for more time sensitive serialized applications, e.g., real-time draws, use:

.. code-block:: pycon

    >>> r = RandomOrgClient(YOUR_API_KEY_HERE, blocking_timeout=2.0, http_timeout=10.0)
    >>> r.generate_signed_integers(5, 0, 10)
    {'random': {u'min': 0, u'max': 10, u'completionTime': u'2014-05-19 14:26:14Z', u'serialNumber': 1482, u'n': 5, u'base': 10, u'hashedApiKey': u'HASHED_KEY_HERE', u'data': [10, 9, 0, 1, 5], u'method': u'generateSignedIntegers', u'replacement': True}, 'data': [10, 9, 0, 1, 5], 'signature': u'SIGNATURE_HERE'}

If obtaining some kind of response instantly is important, a cache should be used. A cache will populate itself as quickly and efficiently as possible allowing pre-obtained randomness to be supplied instantly. If randomness is not available - e.g., the cache is empty - the cache will return an Empty exception allowing the lack of randomness to be handled without delay:

.. code-block:: pycon

    >>> r = RandomOrgClient(YOUR_API_KEY_HERE, blocking_timeout=60.0*60.0, http_timeout=30.0)
    >>> c = r.create_integer_cache(5, 0, 10)
    >>> try:
    ...     c.get()
    ... except Queue.Empty:
    ...     # handle lack of true random number here
    ...     # possibly use a pseudo random number generator
    ...
    [1, 4, 6, 9, 10]

Note that caches don't support signed responses as it is assumed that clients using the signing features want full control over the serial numbering of responses.
	
Finally, it is possible to request live results as-soon-as-possible and without serialization, however this may be more prone to timeout failures as the client must obey the server's advisory delay times if the server is overloaded:

.. code-block:: pycon

    >>> r = RandomOrgClient(YOUR_API_KEY_HERE, blocking_timeout=0.0, http_timeout=10.0, serialized=False)
    >>> r.generate_integers(5, 0, 10)
    [3, 5, 2, 4, 8]

Signature Verification
----------------------
There are two additional methods to generate signature verification URLs and HTML forms (*create_url* and *create_html*) using the random object and signature returned from any of the signed (value generating) methods. The generated URLs and HTML forms link to the same web page that is also shown when a result is verified using the online `Signature Verification Form <https://api.random.org/signatures/form>`_.

Documentation
-------------

For a full list of available randomness generation functions and other features see rdoclient.py documentation and https://api.random.org/json-rpc/4

Tests
-----

Note that to run the accompanying tests the _API_KEY_1 field in test_rdoclient.py must be changed to contain a valid API key. The _API_KEY_2 field does not need to be changed. 
