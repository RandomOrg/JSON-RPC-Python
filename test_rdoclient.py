"""
RANDOM.ORG JSON-RPC API (Release 1) implementation tests.

Run with py.test test_rdoclient.py
"""

import time
import uuid

from datetime import datetime
from queue import Empty

import unittest
import pytest

from rdoclient import *

# _API_KEY_1 = 'YOUR_API_KEY_HERE'
_API_KEY_1 = '59052bc4-840b-4923-96b7-90332167bc8c'
_API_KEY_2 = 'YOUR_API_KEY_HERE'

_FAKE_METHOD = 'fooBar'


class TestRandomOrgSerialClient(unittest.TestCase):
    
    def setUp(self):
        """Create client."""
        self._serial_client = RandomOrgClient(_API_KEY_2, blocking_timeout=30,
                                              serialized=True)
    
    def tearDown(self):
        """Kill all clients."""
        self._serial_client = None
        RandomOrgClient.__key_indexed_instances = {}

    def test_serial_timeout_error(self):
        """Check RandomOrgSendTimeoutError raised when 
        allowed wait time is exceeded for a serial client."""
        
        self._serial_client._advisory_delay = 1000
        
        with pytest.raises(RandomOrgSendTimeoutError):
            response = self._serial_client.generate_integers(10, 0, 10)
        
        self._serial_client._advisory_delay = 1.0


class TestRandomOrgClient(unittest.TestCase):
    
    def setUp(self):
        """Create client."""
        self._client = RandomOrgClient(_API_KEY_1, blocking_timeout=30,
                                       serialized=False)
    
    def tearDown(self):
        """Kill all clients."""
        self._client = None
        RandomOrgClient.__key_indexed_instances = {}

    def test_info(self):
        assert isinstance(self._client.get_requests_left(), int)
        assert isinstance(self._client.get_bits_left(), int)

    def test_api_key_duplication(self):
        """Check new instance isn't created for same api key, 
        and different api key creates different instance."""
        
        duplicate = RandomOrgClient(_API_KEY_1, serialized=False)
        alternative = RandomOrgClient(_API_KEY_2, serialized=True)
        
        assert self._client == duplicate
        assert duplicate != alternative
    
    def test_runtime_error(self):
        """Check RuntimeError raised for one of several possible error codes, 
        in this case we use "method not found"."""
        
        params = { 'apiKey':_API_KEY_1, 'n':10, 'min':0, 'max':10, 'replacement':True }
        request = self._client._generate_request(_FAKE_METHOD, params)
        
        with pytest.raises(RuntimeError):
            response = self._client._send_request(request)
    
    def test_value_error(self):
        """Check ValueError raised for an incorectly 
        parameterised request sent to server."""
        
        with pytest.raises(ValueError):
            response = self._client.generate_integers(10001, 0, 10)
    
    def test_allowance_exceeded_error(self):
        """Check RandomOrgInsufficientRequestsError raised if 
        UTC backoff is in effect."""
        
        code = 402
        message = 'The API key has no requsts left today'
        self._client._backoff = datetime.utcnow().replace(
            day=datetime.utcnow().day+1,
            hour=0, minute=0, second=0, microsecond=0
        )
        self._client._backoff_error = 'Error ' + str(code) + ': ' + message
        
        with pytest.raises(RandomOrgInsufficientRequestsError):
            response = self._client.generate_integers(10, 0, 10)
            
        self._client._backoff = None
        self._client._backoff_error = None
    
    def test_timeout_error(self):
        """Check RandomOrgSendTimeoutError raised when allowed 
        wait time is exceeded."""
        
        self._client._advisory_delay = 1000
        
        with pytest.raises(RandomOrgSendTimeoutError):
            response = self._client.generate_integers(10, 0, 10)
            
        self._client._advisory_delay = 1.0

    def test_generate_integers(self):
        """Check generate integers returns a list of integers."""
        
        response = self._client.generate_integers(10, 0, 10)
        
        assert isinstance(response, list)
        
        for i in response:
            assert isinstance(i, int)
    
    def test_generate_decimal_fractions(self):
        """Check generate decimal fractions returns a list of decimals."""
        
        response = self._client.generate_decimal_fractions(10, 10)
        
        assert isinstance(response, list)
        
        for i in response:
            assert isinstance(i, float)
    
    def test_generate_gaussians(self):
        """Check generate gaussians returns a list of decimals."""
        
        response = self._client.generate_gaussians(10, 10, 0.5, 5)
        
        assert isinstance(response, list)
        
        for i in response:
            assert isinstance(i, float)
    
    def test_generate_strings(self):
        """Check generate strings returns a list of strings."""
        
        response = self._client.generate_strings(10, 10,
                                                 'abcedfghijklmnopqrstuvwxyz')
        
        assert isinstance(response, list)
        
        for i in response:
            print(type(i))
            assert isinstance(i, str)
    
    def test_generate_UUIDs(self):
        """Check generate UUIDs returns a list of UUIDs."""
        
        response = self._client.generate_UUIDs(10)
        
        assert isinstance(response, list)
        
        for i in response:
            assert isinstance(i, uuid.UUID)
    
    def test_generate_blobs(self):
        """Check generate blobs returns a list of blobs."""
        
        response = self._client.generate_blobs(10, 64)
        
        assert isinstance(response, list)
        
        for i in response:
            assert isinstance(i, str)

    def test_generate_signed_integers(self):
        """Check generate signed integers returns a list 
        of integers and can be verified."""
        
        response = self._client.generate_signed_integers(10, 0, 10)
        
        assert isinstance(response, dict)
        
        assert response['data'] is not None
        assert response['random'] is not None
        assert response['signature'] is not None
        
        for i in response['data']:
            assert isinstance(i, int)
        
        assert self._client.verify_signature(response['random'],
                                             response['signature'])
    
    def test_generate_signed_decimal_fractions(self):
        """Check generate signed decimal fractions returns 
        a list of decimals and can be verified."""
        
        response = self._client.generate_signed_decimal_fractions(10, 10)
        
        assert isinstance(response, dict)
        
        assert response['data'] is not None
        assert response['random'] is not None
        assert response['signature'] is not None
        
        for i in response['data']:
            assert isinstance(i, float)
        
        assert self._client.verify_signature(response['random'],
                                             response['signature'])
    
    def test_generate_signed_gaussians(self):
        """Check generate signed gaussians returns a list of 
        decimals and can be verified."""
        
        response = self._client.generate_signed_gaussians(10, 10, 0.5, 5)
        
        assert isinstance(response, dict)
        
        assert response['data'] is not None
        assert response['random'] is not None
        assert response['signature'] is not None
        
        for i in response['data']:
            assert isinstance(i, float)
        
        assert self._client.verify_signature(response['random'],
                                             response['signature'])
    
    def test_generate_signed_strings(self):
        """Check generate signed strings returns a list 
        of strings and can be verified."""
        
        response = self._client.generate_signed_strings(
            10, 10, 'abcedfghijklmnopqrstuvwxyz'
        )
        
        assert isinstance(response, dict)
        
        assert response['data'] is not None
        assert response['random'] is not None
        assert response['signature'] is not None
        
        for i in response['data']:
            assert isinstance(i, str)
        
        assert self._client.verify_signature(response['random'],
                                             response['signature'])
    
    def test_generate_signed_UUIDs(self):
        """Check generate signed UUIDs returns a list of 
        UUIDs and can be verified."""
        
        response = self._client.generate_signed_UUIDs(10)
        
        assert isinstance(response, dict)
        
        assert response['data'] is not None
        assert response['random'] is not None
        assert response['signature'] is not None
        
        for i in response['data']:
            assert isinstance(i, uuid.UUID)
        
        assert self._client.verify_signature(response['random'],
                                             response['signature'])
    
    def test_generate_signed_blobs(self):
        """Check generate signed blobs returns a list of 
        blobs and can be verified."""
        
        response = self._client.generate_signed_blobs(10, 64)
        
        assert isinstance(response, dict)
        
        assert response['data'] is not None
        assert response['random'] is not None
        assert response['signature'] is not None
        
        for i in response['data']:
            assert isinstance(i, str)
        
        assert self._client.verify_signature(response['random'],
                                             response['signature'])

    def test_cache(self):
        """Test empty cache and stop/resume functionality."""
        
        cache = self._client.create_integer_cache(1, 0, 10, cache_size=1)
        cache.stop()
        
        with pytest.raises(Empty):
            print(cache.get())
        
        cache.resume()
        
        got = None
        
        while got is None:
            try:
                got = cache.get()
            except Empty:
                time.sleep(5)
        
        assert isinstance(got, list)
    
    def test_create_integer_cache(self):
        """Check integer cache returns a list of ints on poll."""
        
        cache = self._client.create_integer_cache(1, 0, 10, cache_size=2)
        
        got = None
        
        while got is None:
            try:
                got = cache.get()
            except Empty:
                time.sleep(5)
        
        assert isinstance(got, list)
        
        for g in got:
            assert isinstance(g, int)
    
    def test_create_decimal_fraction_cache(self):
        """Check decimal fraction cache returns a list of decimals on poll."""
        
        cache = self._client.create_decimal_fraction_cache(1, 10, cache_size=2)
        
        got = None
        
        while got is None:
            try:
                got = cache.get()
            except Empty:
                time.sleep(5)
        
        assert isinstance(got, list)
        
        for g in got:
            assert isinstance(g, float)
    
    def test_create_gaussian_cache(self):
        """Check gaussian cache returns a list of decimals on poll."""
        
        cache = self._client.create_gaussian_cache(10, 10, 0.5, 5, cache_size=2)
        
        got = None
        
        while got is None:
            try:
                got = cache.get()
            except Empty:
                time.sleep(5)
        
        assert isinstance(got, list)
        
        for g in got:
            assert isinstance(g, float)
    
    def test_create_string_cache(self):
        """Check string cache returns a list of unicode strings on poll."""
        
        cache = self._client.create_string_cache(10, 10,
                                                 'abcedfghijklmnopqrstuvwxyz',
                                                 cache_size=2)
        
        got = None
        
        while got is None:
            try:
                got = cache.get()
            except Empty:
                time.sleep(5)
        
        assert isinstance(got, list)
        
        for g in got:
            assert isinstance(g, str)
    
    def test_create_UUID_cache(self):
        """Check UUID cache returns a list of UUIDs on poll."""
        
        cache = self._client.create_UUID_cache(10, cache_size=2)
        
        got = None
        
        while got is None:
            try:
                got = cache.get()
            except Empty:
                time.sleep(5)
        
        assert isinstance(got, list)
        
        for g in got:
            assert isinstance(g, uuid.UUID)
    
    def test_create_blob_cache(self):
        """Check blob cache returns a list of unicode blobs on poll."""
        
        cache = self._client.create_blob_cache(10, 64, cache_size=2)
        
        got = None
        
        while got is None:
            try:
                got = cache.get()
            except Empty:
                time.sleep(5)
        
        assert isinstance(got, list)
        
        for g in got:
            assert isinstance(g, str)

    def test_cached_info(self):
        assert isinstance(self._client.get_requests_left(), int)
        assert isinstance(self._client.get_bits_left(), int)
    

