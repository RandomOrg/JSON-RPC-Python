"""
RANDOM.ORG JSON-RPC API (Release 4) implementation.

This is a Python implementation of the RANDOM.ORG JSON-RPC API (R4).
It provides either serialized or unserialized access to both the signed 
and unsigned methods of the API through the RandomOrgClient class. It 
also provides a convenience class through the RandomOrgClient class, 
the RandomOrgCache, for precaching requests.

Classes:

RandomOrgClient -- main class through which API functions are accessed.

RandomOrgCache -- for precaching API responses.

RandomOrgSendTimeoutError -- when request can't be sent in a set time.

RandomOrgKeyNonExistentError -- key does not exist. 

RandomOrgKeyNotRunningError -- key stopped exception.

RandomOrgInsufficientRequestsError -- requests allowance exceeded.

RandomOrgInsufficientBitsError -- bits allowance exceeded.

RandomOrgKeyInvalidAccessError -- key is not valid for the requested 
                                  method.

RandomOrgKeyInvalidVersionError -- key is not valid for the version 
                                   of the API.

RandomOrgTicketNonExistentError -- ticket does not exist.

RandomOrgTicketAPIKeyMismatchError -- ticket cannot be used with 
                                      key specified.

RandomOrgTicketAlreadyUsedError -- ticket has already been used.

RandomOrgTooManySingletonTicketsError -- singleton ticket allowance 
                                         exceeded.
RandomOrgLicenseDataRequiredError -- your API key type requires valid 
                                     license data.
RandomOrgLicenseDataNotAllowedError -- your API key type does not support 
                                       the license data parameter.
"""

from collections import OrderedDict
import base64
import json
import logging
import re
import threading
import time
import sys
import uuid

from datetime import datetime
try:
    # Python 2.7
    from Queue import Queue, Empty
except ImportError:
    # Python 3+
    from queue import Queue, Empty

import requests

# Basic RANDOM.ORG API functions https://api.random.org/json-rpc/4/basic
_INTEGER_METHOD                  = 'generateIntegers'
_INTEGER_SEQUENCES_METHOD        = 'generateIntegerSequences'
_DECIMAL_FRACTION_METHOD         = 'generateDecimalFractions'
_GAUSSIAN_METHOD                 = 'generateGaussians'
_STRING_METHOD                   = 'generateStrings'
_UUID_METHOD                     = 'generateUUIDs'
_BLOB_METHOD                     = 'generateBlobs'
_GET_USAGE_METHOD                = 'getUsage'

# Signed RANDOM.ORG API functions https://api.random.org/json-rpc/4/signed
_SIGNED_INTEGER_METHOD           = 'generateSignedIntegers'
_SIGNED_INTEGER_SEQUENCES_METHOD = 'generateSignedIntegerSequences'
_SIGNED_DECIMAL_FRACTION_METHOD  = 'generateSignedDecimalFractions'
_SIGNED_GAUSSIAN_METHOD          = 'generateSignedGaussians'
_SIGNED_STRING_METHOD            = 'generateSignedStrings'
_SIGNED_UUID_METHOD              = 'generateSignedUUIDs'
_SIGNED_BLOB_METHOD              = 'generateSignedBlobs'
_GET_RESULT_METHOD               = 'getResult'
_CREATE_TICKETS_METHOD           = 'createTickets'
_LIST_TICKETS_METHOD             = 'listTickets'
_GET_TICKET_METHOD               = 'getTicket'
_VERIFY_SIGNATURE_METHOD         = 'verifySignature'

# Blob format literals
_BLOB_FORMAT_BASE64              = 'base64'
_BLOB_FORMAT_HEX                 = 'hex'

# Default backoff to use if no advisoryDelay backoff supplied by server
_DEFAULT_DELAY                   = 1.0

# On request fetch fresh allowance state if current state data is older 
# than this value
_ALLOWANCE_STATE_REFRESH_SECONDS = 3600.0

class RandomOrgSendTimeoutError(Exception):
    """
    RandomOrgClient blocking_timeout exception.
    
    Exception raised by the RandomOrgClient class when blocking_timeout 
    is exceeded before the request can be sent.
    """

class RandomOrgKeyNonExistentError(Exception):
    """
    RandomOrgClient key does not exist.
    
    Exception raised by the RandomOrgClient class when the API key
    specified does not exist. Requests will not complete.
    """

class RandomOrgKeyNotRunningError(Exception):
    """
    RandomOrgClient key stopped exception.
    
    Exception raised by the RandomOrgClient class when its API key
    has been stopped. Requests will not complete while API key is 
    in the stopped state.
    """

class RandomOrgInsufficientRequestsError(Exception):
    """
    RandomOrgClient server requests allowance exceeded exception.
    
    Exception raised by the RandomOrgClient class when its API key's 
    server requests allowance has been exceeded. This indicates that a 
    back-off until midnight UTC is in effect, before which no requests 
    will be sent by the client as no meaningful server responses will 
    be returned.
    """

class RandomOrgInsufficientBitsError(Exception):
    """
    RandomOrgClient server bits allowance exceeded exception.
    
    Exception raised by the RandomOrgClient class when its API key's 
    request has exceeded its remaining server bits allowance. If the 
    client is currently issuing large requests it may be possible to 
    succeed with smaller requests. Use the client's getBitsLeft() call 
    to help determine if an alternative request size is appropriate.
    """

class RandomOrgKeyInvalidAccessError(Exception):
    """
    RandomOrgClient key is not valid for the method requested.
    
    Exception raised by the RandomOrgClient class when its API key 
    is not valid for the method requested. Requests will not complete.
    """

class RandomOrgKeyInvalidVersionError(Exception):
    """
    RandomOrgClient key is not valid for the version of the API invoked. 
    
    Exception raised by the RandomOrgClient class when its API key 
    is not valid for the version of the API invoked. Requests will not 
    complete. 
    """

class RandomOrgTicketNonExistentError(Exception):
    """
    RandomOrgClient ticket does not exist.
    
    Exception raised by the RandomOrgClient class when the ticket 
    specified does not exist. 
    """

class RandomOrgTicketAPIKeyMismatchError(Exception):
    """
    RandomOrgClient ticket exists but is not for the API key specified.
    
    Exception raised by the RandomOrgClient class when the ticket 
    specified exists but does not belong to the API key currently in 
    use. 
    """

class RandomOrgTicketAlreadyUsedError(Exception):
    """
    RandomOrgClient ticket has already been used.
    
    Exception raised by the RandomOrgClient class when the ticket 
    specified has already been used, i.e. it cannot be used for 
    another request. 
    """

class RandomOrgTooManySingletonTicketsError(Exception):
    """
    RandomOrgClient key has reached the maximum number 
    of singleton tickets allowed. 
    
    Exception raised by the RandomOrgClient class when the maximum 
    number of singleton tickets associated with the API key specified 
    has been reached. 
    """

class RandomOrgLicenseDataRequiredError(Exception):
    """
    RandomOrgClient key requires the license data parameter. 
    
    Exception raised by the RandomOrgClient class when the license data 
    parameter of a signed method returning random values is not supplied, 
    but the type of API key specified requires the request to contain valid 
    license data. 
    """
    
class RandomOrgLicenseDataNotAllowedError(Exception):
    """
    RandomOrgClient key does not support license data. 
    
    Exception raised by the RandomOrgClient class when the license data parameter 
    is used but the API key supplied does not support the use of license data.
    """

class RandomOrgCache(object):
    """
    RandomOrgCache for precaching request responses.
    
    Precache for frequently used requests. Instances should only be 
    obtained using RandomOrgClient's create_x_cache methods, never 
    created separately.
    
    This class strives to keep a Queue of response results populated 
    for instant access via its public get method. Work is done by a 
    background Thread, which issues the appropriate request at suitable 
    intervals.
    
    Public methods:
    
    stop -- instruct cache to stop repopulating itself.
    resume -- if cache is stopped, restart repopulation.
    get -- return a response for the request this RandomOrgCache 
        represents or raise a Queue.Empty exception.
    """
    
    def __init__(self, request_function, process_function, request, 
                 cache_size, bulk_request_number=0, request_number=0):
        """
        Constructor.
        
        Initialize class and start Queue population Thread running as a
        daemon. Should only be called by RandomOrgClient's 
        create_x_cache methods.
        
        Keyword arguments:
        
        request_function -- function to send supplied request to server.
        process_function -- function to process result of 
            request_function into expected output.
        request -- request to send to server via request_function.
        cache_size -- number of request responses to try maintain.
        bulk_request_number -- if request is set to be issued in bulk, 
            number of result sets in a bulk request (default 0).
        request_number -- if request is set to be issued in bulk, 
            number of results in a single request (default 0).
        """
        
        self._request_function = request_function
        self._process_function = process_function
        self._request = request
        
        self._queue = Queue(cache_size)
        
        self._bulk_request_number = bulk_request_number
        self._request_number = request_number
        
        # Handle integers with non-decimal base
        if 'base' in self._request['params']:
            self._decimal = self._request['params']['base'] == 10
        else:
            self._decimal = True
        
        # Condition lock to allow notification when an item is consumed
        # or pause state is updated.
        self._lock = threading.Condition()
        self._paused = False
        
        # Thread to keep RandomOrgCache populated.
        self._thread = threading.Thread(target=self._populate_queue)
        self._thread.daemon = True
        self._thread.start()
    
    def _populate_queue(self):
        # Keep issuing requests to server until Queue is full. When 
        # Queue is full if requests are being issued in bulk, wait 
        # until Queue has enough space to accomodate all of a bulk 
        # request before issuing a new request, otherwise issue a new 
        # request every time an item in the Queue has been consumed.
        #
        # Note that requests to the server are blocking, i.e., only one
        # request will be issued by the cache at any given time.
        
        while True:
            while self._paused:
                self._lock.acquire()
                self._lock.wait()
                self._lock.release()
                
            # If we're issuing bulk requests...
            if self._bulk_request_number > 0:
                
                # Is there space for a bulk response in the queue?
                if self._queue.qsize() < (self._queue.maxsize 
                                          - self._bulk_request_number):
                    
                    # Issue and process request and response.
                    try:
                        response = self._request_function(self._request)
                        if self._decimal: 
                            result = self._process_function(response)
                        else:
                            result = self._process_function(response, self._decimal)
                        
                        # Split bulk response into result sets.
                        try:
                            # Python 2.7
                            for i in xrange(0, len(result), self._request_number):
                                self._queue.put(result[i:i+self._request_number])    
                    
                        except NameError:
                            # Python 3+
                            for i in range(0, len(result), self._request_number):
                                self._queue.put(result[i:i+self._request_number])
                        
                    except Exception as e:
                        # Don't handle failures from _request_function()
                        # Just try again later.
                        logging.info("RandomOrgCache populate Exception: " + str(e))
                    
                # No space, sleep and wait for consumed notification.
                else:
                    self._lock.acquire()
                    self._lock.wait()
                    self._lock.release()
            
            # Not in bulk mode, repopulate queue as it empties.
            elif not self._queue.full():
                try:
                    response = self._request_function(self._request)
                    if self._decimal:
                        self._queue.put(self._process_function(response))
                    else:
                        self._queue.put(self._process_function(response, self._decimal))
                except Exception as e:
                    # Don't handle failures from _request_function()
                    # Just try again later.
                    logging.info("RandomOrgCache populate Exception: " + str(e))
            
            # No space, sleep and wait for consumed notification.
            else:
                self._lock.acquire()
                self._lock.wait()
                self._lock.release()
    
    def stop(self):
        """
        Stop cache.
        
        Cache will not continue to populate itself.
        """
        
        self._paused = True
        
        self._lock.acquire()
        self._lock.notify()
        self._lock.release()
    
    def resume(self):
        """
        Resume cache.
        
        Cache will resume populating itself if stopped.
        """
        
        self._paused = False
        
        self._lock.acquire()
        self._lock.notify()
        self._lock.release()
    
    def get(self):
        """
        Get next response.
        
        Get next appropriate response for the request this 
        RandomOrgCache represents or if Queue is empty raise a 
        Queue.Empty exception.
        """
        
        result = self._queue.get(False)
        
        self._lock.acquire()
        self._lock.notify()
        self._lock.release()
        
        return result
    

class RandomOrgClient(object):
    """
    RandomOrgClient main class through which API functions are accessed.
    
    This class provides either serialized or unserialized (determined 
    on class creation) access to both the signed and unsigned methods 
    of the RANDOM.ORG API. These are threadsafe and implemented as 
    blocking remote procedure calls.
    
    If requests are to be issued serially a background Thread will 
    maintain a Queue of requests to process in sequence. 
    
    The class also provides access to creation of a convenience class,
    RandomOrgCache, for precaching API responses when the request is 
    known in advance.
    
    This class will only allow the creation of one instance per API 
    key. If an instance of this class already exists for a given key, 
    that instance will be returned on init instead of a new instance.
    
    This class obeys most of the guidelines set forth in 
    https://api.random.org/json-rpc/4
    All requests respect the server's advisoryDelay returned in any 
    responses, or use _DEFAULT_DELAY if no advisoryDelay is returned. If
    the supplied API key is has exceeded its daily request allowance, 
    this implementation will back off until midnight UTC.
    
    Public methods:
    
    Basic methods for generating randomness, see:
        https://api.random.org/json-rpc/4/basic
    
    generate_integers -- get a list of random integers.
    generate_integer_sequences -- get sequences of random integers.
    generate_decimal_fractions -- get a list of random doubles.
    generate_gaussians -- get a list of random numbers.
    generate_strings -- get a list of random strings.
    generate_UUIDs -- get a list of random UUIDs.
    generate_blobs -- get a list of random blobs.
    
    Signed methods for generating randomness, see:
        https://api.random.org/json-rpc/4/signed
    
    generate_signed_integers -- get a signed response containing a list
        of random integers and a signature.
    generate_signed_integer_sequences -- get a signed response 
        containing sequences of random integers and a signature.    
    generate_signed_decimal_fractions -- get a signed response
        containing a list of random doubles and a signature.
    generate_signed_gaussians -- get a signed response containing a
        list of random numbers and a signature.
    generate_signed_strings -- get a signed response containing a list
        of random strings and a signature.
    generate_signed_UUIDs -- get a signed response containing a list of
        random UUIDs and a signature.
    generate_signed_blobs -- get a signed response containing a list of
        random blobs and a signature.
        
    Retrieving previously generated signed results (within 24h), see:
        https://api.random.org/json-rpc/4/signed#getResult
    
    get_result -- retrieve previously generated signed results using
       a serial number (restricted to within 24 hours after generation)
    
    Tickets for use in methods which generate signed random values, see:
       https://api.random.org/json-rpc/4/signed
    
    create_tickets -- create tickets for use in methods that generate
       random values with signatures
    list_tickets -- obtain a list of tickets of a certain type (singleton,
      head or tail)
    get_ticket -- obtain information on a single ticket
    
    Signature verification for signed methods, see:
        https://api.random.org/json-rpc/4/signed
    
    verify_signature -- verify a response against its signature.
    
    # Methods used to create a cache for any given randomness request.
    
    create_integer_cache -- get a RandomOrgCache from which to obtain a 
        list of random integers.
    create_integer_sequences_cache - get a RandomCache from which to 
        obtain sequences of random integers.
    create_decimal_fraction_cache -- get a RandomOrgCache from which to
        obtain a list of random doubles.
    create_gaussian_cache -- get a RandomOrgCache from which to obtain
        a list of random numbers.
    create_string_cache -- get a RandomOrgCache from which to obtain a
        list of random strings.
    create_UUID_cache -- get a RandomOrgCache from which to obtain a
        list of random UUIDs.
    create_blob_cache -- get a RandomOrgCache from which to obtain a
        list of random blobs.
    
    # Methods for accessing server usage statistics
    
    get_requests_left -- get estimated number of remaining API requests.
    get_bits_left -- get estimated number of bits left.    
    """
    
    # Maintain a dictionary of API keys and their instances.
    __key_indexed_instances = {}
    
    def __new__(cls, *args, **kwds):
        """
        Instance creation.
        
        Ensure only one instance of RandomOrgClient exists per API key.
        Create a new instance if the supplied key isn't already known, 
        otherwise return the previously instantiated one.
        """
        instance = RandomOrgClient.__key_indexed_instances.get(args[0], 
                                                               None)
        
        if instance is None:
            instance = object.__new__(cls)
            RandomOrgClient.__key_indexed_instances[args[0]] = instance
        
        return instance
    
    def __init__(self, api_key, 
                 blocking_timeout=24.0*60.0*60.0, http_timeout=120.0, 
                 serialized=True):
        """
        Constructor.
        
        Initialize class and start serialized request sending Thread 
        running as a daemon if applicable.
        
        Keyword arguments:
        
        api_key -- API key obtained from the RANDOM.ORG website, see: 
            https://api.random.org/api-keys
        blocking_timeout -- maximum time in seconds and fractions of 
            seconds to wait before being allowed to send a request. 
            Note this is a hint not a guarantee. Be advised advisory 
            delay from server must always be obeyed. Supply a value 
            of -1 to allow blocking forever. (default 24.0*60.0*60.0,
            i.e., 1 day)
        http_timeout -- maximum time in seconds and fractions of 
            seconds to wait for the server response to a request.
            (default 120.0).
        serialized -- determines whether or not requests from this 
            instance will be added to a Queue and issued serially or 
            sent when received, obeying any advisory delay (default 
            True).
        """
        
        # __init__ will always be called after __new__, but if an 
        # instance already exists for the API key we want to bail 
        # before actually doing anything in init.
        if not hasattr(self, '_api_key'):
            
            if serialized:
                # set send function
                self._send_request = self._send_serialized_request
            
                # set up the serialized request Queue and Thread
                self._serialized_queue = Queue()
            
                self._serialized_thread = threading.Thread(target=self._threaded_request_sending)
                self._serialized_thread.daemon = True
                self._serialized_thread.start()
            else:
                # set send function
                self._send_request = self._send_unserialized_request
        
            self._api_key = api_key
            self._blocking_timeout = blocking_timeout
            self._http_timeout = http_timeout
        
            # maintain info to obey server advisory delay
            self._advisory_delay_lock = threading.Lock()
            self._advisory_delay = 0
            self._last_response_received_time = 0
        
            # maintain usage statistics from server
            self._requests_left = None
            self._bits_left = None
        
            # backoff info for when API key is detected as not running - 
            # probably because key has exceeded its daily usage limit. 
            # Backoff runs until midnight UTC.
            self._backoff = None
            self._backoff_error = None
            
        else:
            logging.info("Using RandomOrgClient instance already created for key \"" 
                         + api_key + "\"")
    
    
    # Basic methods for generating randomness, see:
    # https://api.random.org/json-rpc/4/basic
    
    def generate_integers(self, n, min, max, replacement=True, base=10, 
                          pregenerated_randomization=None):
        """
        Generate random integers.
        
        Request and return a list (size n) of true random integers 
        within a user-defined range from the server. See:
        https://api.random.org/json-rpc/4/basic#generateIntegers
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many random integers you need. Must be within the 
            [1,1e4] range.
        min -- The lower boundary for the range from which the random 
            numbers will be picked. Must be within the [-1e9,1e9] range.
        max -- The upper boundary for the range from which the random 
            numbers will be picked. Must be within the [-1e9,1e9] range.
        replacement -- Specifies whether the random numbers should be 
            picked with replacement. If True the resulting numbers may 
            contain duplicate values, otherwise the numbers will all be
            unique (default True).
        base -- The base used to display the numbers in the sequences.
            Must be an integer with the value 2, 8, 10 or 16.
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 'min':min, 'max':max, 
                  'replacement':replacement, 'base':base, 
                  'pregeneratedRandomization':pregenerated_randomization }
        request = self._generate_request(_INTEGER_METHOD, params)
        response = self._send_request(request)
        return self._extract_ints(response, base == 10)
    
    def generate_integer_sequences(self, n, length, min, max, replacement=True, 
                                   base=10, pregenerated_randomization=None):
        """
        Generate random integer sequences.
        
        Request and return a list (size n) of uniform or multiform 
        sequences of true random integers 
        within a user-defined range from the server. See:
        https://api.random.org/json-rpc/4/basic#generateIntegerSequences
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many integer sequences you need. Must be within the 
            [1,1e3] range.
        length -- Lengths of the sequences requested. Uniform: Must be 
            an integer within the [1,1e4] range. Multiform: an array of 
            length n where each value is within the [1,1e4] range and 
            the sum of all n values is within the [1,1e4] range.  
        min -- The lower boundary for the range from which the random 
            numbers will be picked. Must be within the [-1e9,1e9] range.
        max -- The upper boundary for the range from which the random 
            numbers will be picked. Must be within the [-1e9,1e9] range.
        replacement -- Specifies whether the random numbers should be 
            picked with replacement. If True the resulting numbers may 
            contain duplicate values, otherwise the numbers will all be
            unique (default True). For multiform sequences this can be
            an array of n boolean values, each specifying whether the 
            sequence identified by its index will be created with (true) 
            or without (false) replacement.
        base -- The base used to display the numbers in the sequences.
            Must be an integer with the value 2, 8, 10 or 16. For multiform
            sequences the values may be an array of length n with values 
            taken from the same set.  
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        """
        params = { 'apiKey':self._api_key, 'n':n, 'length':length, 'min':min, 
                  'max':max, 'replacement':replacement, 'base':base, 
                  'pregeneratedRandomization':pregenerated_randomization }
        request = self._generate_request(_INTEGER_SEQUENCES_METHOD, params)
        response = self._send_request(request)
        return self._extract_int_sequences(response, base == 10)
    
    def generate_decimal_fractions(self, n, decimal_places, replacement=True, 
                                   pregenerated_randomization=None):
        """
        Generate random decimal fractions.
        
        Request and return a list (size n) of true random decimal 
        fractions, from a uniform distribution across the [0,1] 
        interval with a user-defined number of decimal places from the
        server. See:
        https://api.random.org/json-rpc/4/basic#generateDecimalFractions
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many random decimal fractions you need. Must be within
            the [1,1e4] range.
        decimal_places -- The number of decimal places to use. Must be 
            within the [1,20] range.
        replacement -- Specifies whether the random numbers should be 
            picked with replacement. If True the resulting numbers may 
            contain duplicate values, otherwise the numbers will all be
            unique (default True).
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 
                   'decimalPlaces':decimal_places, 'replacement':replacement, 
                   'pregeneratedRandomization':pregenerated_randomization }
        request = self._generate_request(_DECIMAL_FRACTION_METHOD, params)
        response = self._send_request(request)
        return self._extract_doubles(response)
    
    def generate_gaussians(self, n, mean, standard_deviation, significant_digits, 
                           pregenerated_randomization=None):
        """
        Generate random numbers.
        
        Request and return a list (size n) of true random numbers from 
        a Gaussian distribution (also known as a normal distribution). 
        The form uses a Box-Muller Transform to generate the Gaussian 
        distribution from uniformly distributed numbers. See:
        https://api.random.org/json-rpc/4/basic#generateGaussians
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many random numbers you need. Must be within the 
            [1,1e4] range.
        mean -- The distribution's mean. Must be within the [-1e6,1e6] 
            range.
        standard_deviation -- The distribution's standard deviation. 
            Must be within the [-1e6,1e6] range.
        significant_digits -- The number of significant digits to use. 
            Must be within the [2,20] range.
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 'mean':mean,
                   'standardDeviation':standard_deviation, 
                   'significantDigits':significant_digits, 
                   'pregeneratedRandomization':pregenerated_randomization }
        request = self._generate_request(_GAUSSIAN_METHOD, params)
        response = self._send_request(request)
        return self._extract_doubles(response)
    
    def generate_strings(self, n, length, characters, replacement=True, 
                         pregenerated_randomization=None):
        """
        Generate random strings.
        
        Request and return a list (size n) of true random unicode 
        strings from the server. See:
        https://api.random.org/json-rpc/4/basic#generateStrings
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many random strings you need. Must be within the 
            [1,1e4] range.
        length -- The length of each string. Must be within the [1,20] 
            range. All strings will be of the same length.
        characters -- A string that contains the set of characters that
            are allowed to occur in the random strings. The maximum 
            number of characters is 80.
        replacement -- Specifies whether the random strings should be 
            picked with replacement. If True the resulting list of 
            strings may contain duplicates, otherwise the strings will 
            all be unique (default True).
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 'length':length, 
                   'characters':characters, 'replacement':replacement, 
                   'pregeneratedRandomization':pregenerated_randomization }
        request = self._generate_request(_STRING_METHOD, params)
        response = self._send_request(request)
        return self._extract_strings(response)
    
    def generate_UUIDs(self, n, pregenerated_randomization=None):
        """
        Generate random UUIDs.
        
        Request and return a list (size n) of version 4 true random 
        Universally Unique IDentifiers (UUIDs) in accordance with 
        section 4.4 of RFC 4122, from the server. See:
        https://api.random.org/json-rpc/4/basic#generateUUIDs
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many random UUIDs you need. Must be within the [1,1e3]
            range.
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 
                  'pregeneratedRandomization':pregenerated_randomization }
        request = self._generate_request(_UUID_METHOD, params)
        response = self._send_request(request)
        return self._extract_UUIDs(response)
    
    def generate_blobs(self, n, size, format=_BLOB_FORMAT_BASE64, 
                       pregenerated_randomization=None):
        """
        Generate random BLOBs.
        
        Request and return a list (size n) of Binary Large OBjects 
        (BLOBs) as unicode strings containing true random data from the
        server. See:
        https://api.random.org/json-rpc/4/basic#generateBlobs
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many random blobs you need. Must be within the [1,100]
            range.
        size -- The size of each blob, measured in bits. Must be within
            the [1,1048576] range and must be divisible by 8.
        format -- Specifies the format in which the blobs will be 
            returned. Values allowed are _BLOB_FORMAT_BASE64 and 
            _BLOB_FORMAT_HEX (default _BLOB_FORMAT_BASE64).
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 'size':size, 'format':format, 
                  'pregeneratedRandomization':pregenerated_randomization }
        request = self._generate_request(_BLOB_METHOD, params)
        response = self._send_request(request)
        return self._extract_blobs(response)
    
    
    # Signed methods for generating randomness, see:
    # https://api.random.org/json-rpc/4/signed
    
    def generate_signed_integers(self, n, min, max, replacement=True, 
                                 base=10, pregenerated_randomization=None, 
                                 license_data=None, user_data=None, 
                                 ticket_id=None):
        """
        Generate digitally signed random integers.
        
        Request a list (size n) of true random integers within a 
        user-defined range from the server. Returns a dictionary object 
        with the parsed integer list mapped to 'data', the original 
        response mapped to 'random', and the response's signature 
        mapped to 'signature'. See:
        https://api.random.org/json-rpc/4/signed#generateSignedIntegers
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a RandomOrgTicketNonExistentError if the ticket used 
        does not exist.

        Raises a RandomOrgTicketAPIKeyMismatchError if the ticket used 
        exists but is not associated with the API key specified.

        Raises a RandomOrgTicketAlreadyUsedError if a ticket has already 
        been used.
        
        Raises a RandomOrgTooManySingletonTicketsError when the maximum 
        number of singleton tickets for this API key has been reached.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many random integers you need. Must be within the 
            [1,1e4] range.
        min -- The lower boundary for the range from which the random 
            numbers will be picked. Must be within the [-1e9,1e9] range.
        max -- The upper boundary for the range from which the random 
            numbers will be picked. Must be within the [-1e9,1e9] range.
        replacement -- Specifies whether the random numbers should be 
            picked with replacement. If True the resulting numbers may 
            contain duplicate values, otherwise the numbers will all be
            unique (default True).
        base -- The base used to display the numbers in the sequences.
            Must be an integer with the value 2, 8, 10 or 16.
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        license_data -- Allows the caller to include data of relevance to 
            the license that is associated with the API Key.This is mandatory
            for API Keys with the license type "Flexible Gambling" and follows
            the format { "maxPayout": { "currency": "XTS", "amount": 0.0 } }. 
            This information is used in licensing requested random values and 
            in billing. The currently supported currencies are: "USD".
        user_data -- Contains an optional object that will be included 
            in unmodified form in the signed response along with the 
            random data. If an object is present, its maximum size in 
            encoded (string) form is 1,000 characters.
        ticket_id -- A string with ticket identifier obtained via the 
            create_tickets method. Specifying a value for ticket_id will 
            cause RANDOM.ORG to record that the ticket was used to generate 
            the requested random values. Each ticket can only be used once.
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 'min':min, 'max':max, 
                  'replacement':replacement, 'base':base, 
                  'pregeneratedRandomization':pregenerated_randomization, 
                  'licenseData':license_data, 'userData':user_data, 
                  'ticketId':ticket_id }
        request = self._generate_request(_SIGNED_INTEGER_METHOD, params)
        response = self._send_request(request)
        return self._extract_signed_response(response, self._extract_ints, base == 10)
    
    def generate_signed_integer_sequences(self, n, length, min, max, 
                                          replacement=True, base=10, 
                                          pregenerated_randomization=None, 
                                          license_data=None, user_data=None, 
                                          ticket_id=None):
        """
        Generate digitally signed sequences of random integers.
        
        Request a list (size n) of sequences of true random integers within 
        a user-defined range from the server. Returns a dictionary object 
        with the parsed integer list mapped to 'data', the original 
        response mapped to 'random', and the response's signature 
        mapped to 'signature'. See:
        https://api.random.org/json-rpc/4/signed#generateSignedIntegerSequences
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a RandomOrgTicketNonExistentError if the ticket used 
        does not exist.

        Raises a RandomOrgTicketAPIKeyMismatchError if the ticket used 
        exists but is not associated with the API key specified.

        Raises a RandomOrgTicketAlreadyUsedError if a ticket has already 
        been used.
        
        Raises a RandomOrgTooManySingletonTicketsError when the maximum 
        number of singleton tickets for this API key has been reached.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many integer sequences you need. Must be within the 
            [1,1e3] range.
        length -- Lengths of the sequences requested. Uniform: Must be 
            an integer within the [1,1e4] range. Multiform: an array of 
            length n where each value is within the [1,1e4] range and 
            the sum of all n values is within the [1,1e4] range.  
        min -- The lower boundary for the range from which the random 
            numbers will be picked. Must be within the [-1e9,1e9] range.
        max -- The upper boundary for the range from which the random 
            numbers will be picked. Must be within the [-1e9,1e9] range.
        replacement -- Specifies whether the random numbers should be 
            picked with replacement. If True the resulting numbers may 
            contain duplicate values, otherwise the numbers will all be
            unique (default True). For multiform sequences this can be
            an array of n boolean values, each specifying whether the 
            sequence identified by its index will be created with (true) 
            or without (false) replacement.
        base -- The base used to display the numbers in the sequences.
            Must be an integer with the value 2, 8, 10 or 16. For multiform
            sequences the values may be an array of length n with values 
            taken from the same set.
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        license_data -- Allows the caller to include data of relevance to 
            the license that is associated with the API Key.This is mandatory
            for API Keys with the license type "Flexible Gambling" and follows
            the format { "maxPayout": { "currency": "XTS", "amount": 0.0 } }. 
            This information is used in licensing requested random values and 
            in billing. The currently supported currencies are: "USD".
        user_data -- Contains an optional object that will be included 
            in unmodified form in the signed response along with the 
            random data. If an object is present, its maximum size in 
            encoded (string) form is 1,000 characters.
        ticket_id -- A string with ticket identifier obtained via the 
            create_tickets method. Specifying a value for ticket_id will 
            cause RANDOM.ORG to record that the ticket was used to generate 
            the requested random values. Each ticket can only be used once.
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 'length':length, 'min':min,
                  'max':max, 'replacement':replacement, 'base':base, 
                  'pregeneratedRandomization':pregenerated_randomization, 
                  'licenseData':license_data, 'userData':user_data, 
                  'ticketId':ticket_id }
        request = self._generate_request(_SIGNED_INTEGER_SEQUENCES_METHOD, params)
        response = self._send_request(request)
        return self._extract_signed_response(response, self._extract_int_sequences, 
                                             base == 10)
    
    def generate_signed_decimal_fractions(self, n, decimal_places, 
                                          replacement=True, 
                                          pregenerated_randomization=None, 
                                          license_data=None, user_data=None, 
                                          ticket_id=None):
        """
        Generate digitally signed random decimal fractions.
        
        Request a list (size n) of true random decimal fractions, from
        a uniform distribution across the [0,1] interval with a 
        user-defined number of decimal places from the server. Returns 
        a dictionary object with the parsed decimal fraction list 
        mapped to 'data', the original response mapped to 'random', and
        the response's signature mapped to 'signature'. See:
        https://api.random.org/json-rpc/4/signed#generateSignedDecimalFractions
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a RandomOrgTicketNonExistentError if the ticket used 
        does not exist.

        Raises a RandomOrgTicketAPIKeyMismatchError if the ticket used 
        exists but is not associated with the API key specified.

        Raises a RandomOrgTicketAlreadyUsedError if a ticket has already 
        been used.
        
        Raises a RandomOrgTooManySingletonTicketsError when the maximum 
        number of singleton tickets for this API key has been reached.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many random decimal fractions you need. Must be within
            the [1,1e4] range.
        decimal_places -- The number of decimal places to use. Must be 
            within the [1,20] range.
        replacement -- Specifies whether the random numbers should be 
            picked with replacement. If True the resulting numbers may 
            contain duplicate values, otherwise the numbers will all be
            unique (default True).
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        license_data -- Allows the caller to include data of relevance to 
            the license that is associated with the API Key.This is mandatory
            for API Keys with the license type "Flexible Gambling" and follows
            the format { "maxPayout": { "currency": "XTS", "amount": 0.0 } }. 
            This information is used in licensing requested random values and 
            in billing. The currently supported currencies are: "USD".
        user_data -- Contains an optional object that will be included 
            in unmodified form in the signed response along with the 
            random data. If an object is present, its maximum size in 
            encoded (string) form is 1,000 characters.
        ticket_id -- A string with ticket identifier obtained via the 
            create_tickets method. Specifying a value for ticket_id will 
            cause RANDOM.ORG to record that the ticket was used to generate 
            the requested random values. Each ticket can only be used once.
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 
                   'decimalPlaces':decimal_places, 'replacement':replacement,
                   'pregeneratedRandomization':pregenerated_randomization, 
                   'licenseData':license_data, 'userData':user_data, 
                   'ticketId':ticket_id }
        request = self._generate_request(_SIGNED_DECIMAL_FRACTION_METHOD, params)
        response = self._send_request(request)
        return self._extract_signed_response(response, self._extract_doubles)
    
    def generate_signed_gaussians(self, n, mean, standard_deviation, 
                                  significant_digits, 
                                  pregenerated_randomization=None, 
                                  license_data=None, user_data=None, 
                                  ticket_id=None):
        """
        Generate digitally signed random numbers.
        
        Request a list (size n) of true random numbers from a Gaussian 
        distribution (also known as a normal distribution). The form 
        uses a Box-Muller Transform to generate the Gaussian 
        distribution from uniformly distributed numbers. Returns a 
        dictionary object with the parsed random number list mapped to
        'data', the original response mapped to 'random', and the 
        response's signature mapped to 'signature'. See:
        https://api.random.org/json-rpc/4/signed#generateSignedGaussians
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a RandomOrgTicketNonExistentError if the ticket used 
        does not exist.

        Raises a RandomOrgTicketAPIKeyMismatchError if the ticket used 
        exists but is not associated with the API key specified.

        Raises a RandomOrgTicketAlreadyUsedError if a ticket has already 
        been used.
        
        Raises a RandomOrgTooManySingletonTicketsError when the maximum 
        number of singleton tickets for this API key has been reached.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many random numbers you need. Must be within the 
            [1,1e4] range.
        mean -- The distribution's mean. Must be within the [-1e6,1e6] 
            range.
        standard_deviation -- The distribution's standard deviation. 
            Must be within the [-1e6,1e6] range.
        significant_digits -- The number of significant digits to use. 
            Must be within the [2,20] range.
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        license_data -- Allows the caller to include data of relevance to 
            the license that is associated with the API Key.This is mandatory
            for API Keys with the license type "Flexible Gambling" and follows
            the format { "maxPayout": { "currency": "XTS", "amount": 0.0 } }. 
            This information is used in licensing requested random values and 
            in billing. The currently supported currencies are: "USD".
        user_data -- Contains an optional object that will be included 
            in unmodified form in the signed response along with the 
            random data. If an object is present, its maximum size in 
            encoded (string) form is 1,000 characters.
        ticket_id -- A string with ticket identifier obtained via the 
            create_tickets method. Specifying a value for ticket_id will 
            cause RANDOM.ORG to record that the ticket was used to generate 
            the requested random values. Each ticket can only be used once.
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 'mean':mean,
                   'standardDeviation':standard_deviation, 
                   'significantDigits':significant_digits, 
                   'pregeneratedRandomization':pregenerated_randomization, 
                   'licenseData':license_data, 'userData':user_data, 
                   'ticketId':ticket_id }
        request = self._generate_request(_SIGNED_GAUSSIAN_METHOD, params)
        response = self._send_request(request)
        return self._extract_signed_response(response, self._extract_doubles)
    
    def generate_signed_strings(self, n, length, characters, 
                                replacement=True, 
                                pregenerated_randomization=None, 
                                license_data=None, user_data=None, 
                                ticket_id=None):
        """
        Generate digitally signed random strings.
        
        Request a list (size n) of true random strings from the server.
        Returns a dictionary object with the parsed random string list 
        mapped to 'data', the original response mapped to 'random', and
        the response's signature mapped to 'signature'. See:
        https://api.random.org/json-rpc/4/signed#generateSignedStrings
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a RandomOrgTicketNonExistentError if the ticket used 
        does not exist.

        Raises a RandomOrgTicketAPIKeyMismatchError if the ticket used 
        exists but is not associated with the API key specified.

        Raises a RandomOrgTicketAlreadyUsedError if a ticket has already 
        been used.
        
        Raises a RandomOrgTooManySingletonTicketsError when the maximum 
        number of singleton tickets for this API key has been reached.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many random strings you need. Must be within the 
            [1,1e4] range.
        length -- The length of each string. Must be within the [1,20] 
            range. All strings will be of the same length.
        characters -- A string that contains the set of characters that
            are allowed to occur in the random strings. The maximum 
            number of characters is 80.
        replacement -- Specifies whether the random strings should be 
            picked with replacement. If True the resulting list of 
            strings may contain duplicates, otherwise the strings will 
            all be unique (default True).
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        license_data -- Allows the caller to include data of relevance to 
            the license that is associated with the API Key.This is mandatory
            for API Keys with the license type "Flexible Gambling" and follows
            the format { "maxPayout": { "currency": "XTS", "amount": 0.0 } }. 
            This information is used in licensing requested random values and 
            in billing. The currently supported currencies are: "USD".
        user_data -- Contains an optional object that will be included 
            in unmodified form in the signed response along with the 
            random data. If an object is present, its maximum size in 
            encoded (string) form is 1,000 characters.
        ticket_id -- A string with ticket identifier obtained via the 
            create_tickets method. Specifying a value for ticket_id will 
            cause RANDOM.ORG to record that the ticket was used to generate 
            the requested random values. Each ticket can only be used once.
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 'length':length, 
                   'characters':characters, 'replacement':replacement, 
                   'pregeneratedRandomization':pregenerated_randomization, 
                   'licenseData':license_data, 'userData':user_data, 
                   'ticketId':ticket_id }
        request = self._generate_request(_SIGNED_STRING_METHOD, params)
        response = self._send_request(request)
        return self._extract_signed_response(response, self._extract_strings)
    
    def generate_signed_UUIDs(self, n, pregenerated_randomization=None, 
                              license_data=None, user_data=None, 
                              ticket_id=None):
        """
        Generate digitally signed random UUIDs.
        
        Request a list (size n) of version 4 true random Universally 
        Unique IDentifiers (UUIDs) in accordance with section 4.4 of 
        RFC 4122, from the server. Returns a dictionary object with the
        parsed random UUID list mapped to 'data', the original response
        mapped to 'random', and the response's signature mapped to 
        'signature'. See:
        https://api.random.org/json-rpc/4/signed#generateSignedUUIDs
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a RandomOrgTicketNonExistentError if the ticket used 
        does not exist.

        Raises a RandomOrgTicketAPIKeyMismatchError if the ticket used 
        exists but is not associated with the API key specified.

        Raises a RandomOrgTicketAlreadyUsedError if a ticket has already 
        been used.
        
        Raises a RandomOrgTooManySingletonTicketsError when the maximum 
        number of singleton tickets for this API key has been reached.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many random UUIDs you need. Must be within the [1,1e3]
            range.
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        license_data -- Allows the caller to include data of relevance to 
            the license that is associated with the API Key.This is mandatory
            for API Keys with the license type "Flexible Gambling" and follows
            the format { "maxPayout": { "currency": "XTS", "amount": 0.0 } }. 
            This information is used in licensing requested random values and 
            in billing. The currently supported currencies are: "USD".
        user_data -- Contains an optional object that will be included 
            in unmodified form in the signed response along with the 
            random data. If an object is present, its maximum size in 
            encoded (string) form is 1,000 characters.
        ticket_id -- A string with ticket identifier obtained via the 
            create_tickets method. Specifying a value for ticket_id will 
            cause RANDOM.ORG to record that the ticket was used to generate 
            the requested random values. Each ticket can only be used once.
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 
                  'pregeneratedRandomization':pregenerated_randomization, 
                  'licenseData':license_data, 'userData':user_data, 
                  'ticketId':ticket_id }
        request = self._generate_request(_SIGNED_UUID_METHOD, params)
        response = self._send_request(request)
        return self._extract_signed_response(response, self._extract_UUIDs)
    
    def generate_signed_blobs(self, n, size, format=_BLOB_FORMAT_BASE64, 
                              pregenerated_randomization=None, 
                              license_data=None, user_data=None, 
                              ticket_id=None):
        """
        Generate digitally signed random BLOBs.
        
        Request a list (size n) of Binary Large OBjects (BLOBs) 
        containing true random data from the server. Returns a 
        dictionary object with the parsed random BLOB list mapped to 
        'data', the original response mapped to 'random', and the 
        response's signature mapped to 'signature'. See:
        https://api.random.org/json-rpc/4/signed#generateSignedBlobs
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a RandomOrgTicketNonExistentError if the ticket used 
        does not exist.

        Raises a RandomOrgTicketAPIKeyMismatchError if the ticket used 
        exists but is not associated with the API key specified.

        Raises a RandomOrgTicketAlreadyUsedError if a ticket has already 
        been used.
        
        Raises a RandomOrgTooManySingletonTicketsError when the maximum 
        number of singleton tickets for this API key has been reached.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- How many random blobs you need. Must be within the [1,100]
            range.
        size -- The size of each blob, measured in bits. Must be within
            the [1,1048576] range and must be divisible by 8.
        format -- Specifies the format in which the blobs will be 
            returned. Values allowed are _BLOB_FORMAT_BASE64 and 
            _BLOB_FORMAT_HEX (default _BLOB_FORMAT_BASE64).
        pregenerated_randomization -- Allows the client to specify that 
            the random values should be generated from a pregenerated, 
            historical randomization instead of a one-time on-the-fly 
            randomization. There are three possible cases:
            - null: the standard way of calling for random values, i.e.
              true randomness is generated and discarded afterwards
            - date: RANDOM.ORG uses historical true randomness generated 
              on the corresponding date (past or present, format: 
              { "date": "YYYY-MM-DD" })
            - id: RANDOM.ORG uses historical true randomness derived 
              from the corresponding identifier in a deterministic 
              manner. Format: { "id": "PERSISTENT-IDENTIFIER" } where
              "PERSISTENT-IDENTIFIER" is a string with length in the 
              [1,64] range
        license_data -- Allows the caller to include data of relevance to 
            the license that is associated with the API Key.This is mandatory
            for API Keys with the license type "Flexible Gambling" and follows
            the format { "maxPayout": { "currency": "XTS", "amount": 0.0 } }. 
            This information is used in licensing requested random values and 
            in billing. The currently supported currencies are: "USD".
        user_data -- Contains an optional object that will be included 
            in unmodified form in the signed response along with the 
            random data. If an object is present, its maximum size in 
            encoded (string) form is 1,000 characters.
        ticket_id -- A string with ticket identifier obtained via the 
            create_tickets method. Specifying a value for ticket_id will 
            cause RANDOM.ORG to record that the ticket was used to generate 
            the requested random values. Each ticket can only be used once.
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 'size':size, 
                  'format':format, 
                  'pregeneratedRandomization':pregenerated_randomization, 
                  'licenseData':license_data, 'userData':user_data, 
                  'ticketId':ticket_id }
        request = self._generate_request(_SIGNED_BLOB_METHOD, params)
        response = self._send_request(request)
        return self._extract_signed_response(response, self._extract_blobs)
    
    def get_result(self, serial_number):
        """
        Retrieve previously generated results. 
        
        Retrieve results generated using signed methods within the last 
        24 hours using its serialNumber. See:
        https://api.random.org/json-rpc/4/signed#getResult  
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        serial_number -- An integer containing the serial number 
            associated with the response you wish to retrieve.
        
        """
        params = { 'apiKey':self._api_key, 'serialNumber':serial_number}
        request = self._generate_request(_GET_RESULT_METHOD, params)
        response = self._send_request(request)
        return self._extract_signed_response(response, self._extract_response)
    
    def create_tickets(self, n, show_result):
        """
        Create tickets to be used in signed value-generating methods. 
        
        This method creates a number of tickets. The tickets can be 
        used in one of the methods that generate random values. See:
        https://api.random.org/json-rpc/4/signed#createTickets
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped. 
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        n -- The number of tickets requested. This must be a number 
            in the [1, 50] range.
        showResult -- A boolean value that determines how much information 
            calls to get_ticket will return. If show_result is false, getTicket 
            will return only the basic ticket information. If show_result is 
            true, the full random and signature objects from the response that 
            was used to satisfy the ticket is returned.        
        """
        
        params = { 'apiKey':self._api_key, 'n':n, 'showResult':show_result }
        request = self._generate_request(_CREATE_TICKETS_METHOD, params)
        response = self._send_request(request)
        return self._extract_tickets(response)
    
    def list_tickets(self, ticket_type):
        """
        Obtain information about tickets linked with your API key.
        
        This method obtains information about tickets that exist 
        for a given API key. See:
        https://api.random.org/json-rpc/4/signed#listTickets
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped. 
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        ticket_type -- A string describing the type of tickets you want to obtain 
            information about. Possible values are singleton, head and tail. 
            Specifying singleton will cause list_tickets to return tickets that 
            have no previous or next tickets. Specifying head will return tickets 
            that do not have a previous ticket but that do have a next ticket. 
            Specifying tail will cause list_tickets to return tickets that have a 
            previous ticket but do not have a next ticket. 
        """
        params = { 'apiKey':self._api_key, 'ticketType':ticket_type }
        request = self._generate_request(_LIST_TICKETS_METHOD, params)
        response = self._send_request(request)
        return self._extract_tickets(response)
    
    def get_ticket(self, ticket_id):
        """
        Obtain information about a single ticket. 
        
        This method obtains information about a single ticket. If
        the ticket has showResult set to true and has been used, 
        get ticket will return the values generated. See:
        https://api.random.org/json-rpc/4/signed#getTicket
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped. 
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a RandomOrgTicketNonExistentError if the ticket used 
        does not exist.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        ticket_id -- A string containing a ticket identifier returned by a prior 
        call to the create_tickets method.
        """
        
        params = { 'ticketId':ticket_id }
        request = self._generate_request(_GET_TICKET_METHOD, params)
        response = self._send_request(request)
        return self._extract_tickets(response)
    
    
    # Signature verification for signed methods, see:
    # https://api.random.org/json-rpc/4/signed
    
    def verify_signature(self, random, signature):
        """
        Verify the signature of a previously received response.
        
        Verify the signature of a response previously received from one
        of the methods in the Signed API with the server. This is used
        to examine the authenticity of numbers. Return True on 
        verification success. See:
        https://api.random.org/json-rpc/4/signed#verifySignature
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped.
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a RandomOrgKeyInvalidAccessError if this API key is not 
        valid for this method.
        
        Raises a RandomOrgKeyInvalidVersionError if this API key is not 
        valid for the version of the API invoked.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        
        Keyword arguments:
        
        random -- The random field from a response returned by 
        RANDOM.ORG through one of the Signed API methods.
        signature -- The signature field from the same response that 
        the random field originates from.
        """
        
        params = { 'random':random, 'signature':signature }
        request = self._generate_request(_VERIFY_SIGNATURE_METHOD, params)
        response = self._send_request(request)
        return self._extract_verification_response(response)
        
    def create_url(self, random, signature):
        """
        Create the URL for the signature verification page of a signed
        response.
        
        Create the URL for the signature verification page of a response
        previously received from one of the methods in the Signed API with
        the server. The web-page accessible from this URL will contain the
        details of the response used in this method, provided that the
        signature can be verified. This URL is also shown under "Show
        Technical Details" when the online Signature Verification Form is
        used to validate a signature. See:
        https://api.random.org/signatures/form
        
        Please note that, when using Python 2.7, the URL generated by this
        method may differ from that shown when using the online Signature
        Verification Form. This is because dictionaries in Python 2.7 are
        not ordered and the encoded string will reflect this. The URL will
        still work as expected.
        
        Raises a ValueError when the length of the generated URL exceeds
        the maximum length allowed (2,046 characters). The random object
        may be too large, i.e., too many random values were requested.
        
        Keyword arguments:
        
        random -- The random field from a response returned by 
        RANDOM.ORG through one of the Signed API methods.
        signature -- The signature field from the same response that 
        the random field originates from.
        """
        # ensure that input is formatted correctly and is url-safe
        random = self._url_formatting(random)
        signature = self._url_formatting(signature)
    
        # create full url
        url = 'https://api.random.org/signatures/form?format=json'   
        url += '&random=' + random
        url += '&signature=' + signature
    
        # throw an error is the maximum length allowed (2,046 characters)
        # is exceeded
        if len(url) > 2046:
            raise ValueError('Error: URL exceeds maximum length (2,046 characters).')
        
        return url
    
    def create_html(self, random, signature):
        """
        Create the HTML form for the signature verification page of a signed
        response.
        
        Create the HTML form for the signature verification page of a response
        previously received from one of the methods in the Signed API with
        the server. The web-page accessible from the "Validate" button created
        will contain the details of the response used in this method, provided
        that the signature can be verified. The same HTML form is also shown
        under "Show Technical Details" when the online Signature Verification
        Form is used to validate a signature. See:
        https://api.random.org/signatures/form
        
        Please note that, when using Python 2.7, the HTML form generated by
        this method may differ from that shown when using the online Signature
        Verification Form. This is because dictionaries in Python 2.7 are
        not ordered and the "random" input field will reflect this. The form
        will still work as expected.
        
        Keyword arguments:
        
        random -- The random field from a response returned by 
        RANDOM.ORG through one of the Signed API methods.
        signature -- The signature field from the same response that 
        the random field originates from.
        """
        # if necessary, turn the random object (dict) into a string
        if isinstance(random, dict):
            random = json.dumps(random)
    
        s = '<form action=\'https://api.random.org/signatures/form\' method=\'post\'>\n'
        s += '  ' + self._input_html('hidden', 'format', 'json') + '\n'
        s += '  ' + self._input_html('hidden', 'random', str(random)) + '\n'
        s += '  ' + self._input_html('hidden', 'signature', signature) + '\n'
        s += '  <input type=\'submit\' value=\'Validate\' />\n</form>'
    
        return s
    
    # Methods used to create a cache for any given randomness request.
    
    def create_integer_cache(self, n, min, max, replacement=True, 
                             base=10, cache_size=20):
        """
        Get a RandomOrgCache to obtain random integers.
        
        The RandomOrgCache can be polled for new results conforming to 
        the output format of the input request. See output of 
        generate_integers() for the return value of a poll on 
        RandomOrgCache.
        
        Keyword arguments:
        
        n -- How many random integers you need. Must be within the 
            [1,1e4] range.
        min -- The lower boundary for the range from which the random 
            numbers will be picked. Must be within the [-1e9,1e9] range.
        max -- The upper boundary for the range from which the random 
            numbers will be picked. Must be within the [-1e9,1e9] range.
        replacement -- Specifies whether the random numbers should be 
            picked with replacement. If True the resulting numbers may 
            contain duplicate values, otherwise the numbers will all be
            unique (default True).
        base -- The base used to display the numbers in the sequences.
            Must be an integer with the value 2, 8, 10 or 16.
        cache_size -- Number of result-sets for the cache to try to 
            maintain at any given time (default 20, minimum 2).
        """
        
        if cache_size < 2:
            cache_size = 2
            
        # if possible, make requests more efficient by bulk-ordering 
        # from the server. Either 5 sets of items at a time, or 
        # cache_size/2 if 5 >= cache_size.
        if replacement:
            bulk_n = cache_size//2 if 5 >= cache_size else 5
            params = { 'apiKey':self._api_key, 'n':bulk_n*n, 
                       'min':min, 'max':max, 'replacement':replacement, 
                       'base':base }
        
        # not possible to make the request more efficient
        else:
            bulk_n = 0
            params = { 'apiKey':self._api_key, 'n':n, 
                       'min':min, 'max':max, 'replacement':replacement, 
                       'base':base }
        
        # get the request object for use in all requests from this cache
        request = self._generate_request(_INTEGER_METHOD, params)
        
        return RandomOrgCache(self._send_request, self._extract_ints, 
                              request, cache_size, bulk_n, n)
    
    def create_integer_sequences_cache(self, n, length, min, max, 
                                       replacement=True, base=10, 
                                       cache_size=20):
        """
        Get a RandomOrgCache to obtain random integer sequences.
        
        The RandomOrgCache can be polled for new results conforming to 
        the output format of the input request. See output of 
        generate_integers() for the return value of a poll on 
        RandomOrgCache.
        
        Keyword arguments:
        
        n -- How many sequences of random integers you need. Must be 
            within the [1,1e3] range.
        length -- Lengths of the sequences requested. Uniform: Must be 
            an integer within the [1,1e4] range. Multiform: an array of 
            length n where each value is within the [1,1e4] range and 
            the sum of all n values is within the [1,1e4] range.  
        min -- The lower boundary for the range from which the random 
            numbers will be picked. Must be within the [-1e9,1e9] range.
        max -- The upper boundary for the range from which the random 
            numbers will be picked. Must be within the [-1e9,1e9] range.
        replacement -- Specifies whether the random numbers should be 
            picked with replacement. If True the resulting numbers may 
            contain duplicate values, otherwise the numbers will all be
            unique (default True).
        base -- The base used to display the numbers in the sequences.
            Must be an integer with the value 2, 8, 10 or 16.
        cache_size -- Number of result-sets for the cache to try to 
            maintain at any given time (default 20, minimum 2).
        """
        
        if cache_size < 2:
            cache_size = 2
            
        # if possible, make requests more efficient by bulk-ordering 
        # from the server. Either 5 sets of items at a time, or 
        # cache_size/2 if 5 >= cache_size.
        if replacement:
            bulk_n = cache_size//2 if 5 >= cache_size else 5
            params = { 'apiKey':self._api_key, 'n':bulk_n*n, 
                      'length':length, 'min':min, 'max':max, 
                      'replacement':replacement, 'base':base }
        
        # not possible to make the request more efficient
        else:
            bulk_n = 0
            params = { 'apiKey':self._api_key, 'n':n, 'length':length, 
                       'min':min, 'max':max, 'replacement':replacement, 
                       'base':base }
        
        # get the request object for use in all requests from this cache
        request = self._generate_request(_INTEGER_SEQUENCES_METHOD, params)
        
        return RandomOrgCache(self._send_request, 
                              self._extract_int_sequences, 
                              request, cache_size, bulk_n, n)
    
    def create_decimal_fraction_cache(self, n, decimal_places, replacement=True, 
                                       cache_size=20):
        """
        Get a RandomOrgCache to obtain random decimal fractions.
        
        The RandomOrgCache can be polled for new results conforming to 
        the output format of the input request. See output of 
        generate_decimal_fractions() for the return value of a poll on 
        RandomOrgCache.
        
        Keyword arguments:
       
        n -- How many random decimal fractions you need. Must be within
            the [1,1e4] range.
        decimal_places -- The number of decimal places to use. Must be 
            within the [1,20] range.
        replacement -- Specifies whether the random numbers should be 
            picked with replacement. If True the resulting numbers may 
            contain duplicate values, otherwise the numbers will all be 
            unique (default True).
        cache_size -- Number of result-sets for the cache to try to 
            maintain at any given time (default 20, minimum 2).
        """
        
        if cache_size < 2:
            cache_size = 2
       
        # if possible, make requests more efficient by bulk-ordering 
        # from the server. Either 5 sets of items at a time, or 
        # cache_size/2 if 5 >= cache_size.
        if replacement:
            bulk_n = cache_size//2 if 5 >= cache_size else 5
            params = { 'apiKey':self._api_key, 'n':bulk_n*n, 
                       'decimalPlaces':decimal_places, 
                       'replacement':replacement }
        
        # not possible to make the request more efficient
        else:
            bulk_n = 0
            params = { 'apiKey':self._api_key, 'n':n, 
                       'decimalPlaces':decimal_places, 
                       'replacement':replacement }
        
        # get the request object for use in all requests from this cache
        request = self._generate_request(_DECIMAL_FRACTION_METHOD, params)
        
        return RandomOrgCache(self._send_request, self._extract_doubles, 
                              request, cache_size, bulk_n, n)
    
    def create_gaussian_cache(self, n, mean, standard_deviation, 
                              significant_digits, cache_size=20):
        """
        Get a RandomOrgCache to obtain random numbers.
        
        The RandomOrgCache can be polled for new results conforming to 
        the output format of the input request. See output of 
        generate_gaussians() for the return value of a poll on 
        RandomOrgCache.
        
        Keyword arguments:
        
        n -- How many random numbers you need. Must be within the 
            [1,1e4] range.
        mean -- The distribution's mean. Must be within the [-1e6,1e6] 
            range.
        standard_deviation -- The distribution's standard deviation. 
            Must be within the [-1e6,1e6] range.
        significant_digits -- The number of significant digits to use. 
            Must be within the [2,20] range.
        cache_size -- Number of result-sets for the cache to try to 
            maintain at any given time (default 20, minimum 2).
        """
        
        if cache_size < 2:
            cache_size = 2
        
        # make requests more efficient by bulk-ordering from the 
        # server. Either 5 sets of items at a time, or cache_size/2 
        # if 5 >= cache_size.
        bulk_n = cache_size//2 if 5 >= cache_size else 5
        params = { 'apiKey':self._api_key, 'n':bulk_n*n, 'mean':mean,
                   'standardDeviation':standard_deviation, 
                   'significantDigits':significant_digits }
        
        # get the request object for use in all requests from this cache
        request = self._generate_request(_GAUSSIAN_METHOD, params)
        
        return RandomOrgCache(self._send_request, self._extract_doubles,
                              request, cache_size, bulk_n, n)
    
    def create_string_cache(self, n, length, characters, replacement=True, 
                            cache_size=20):
        """
        Get a RandomOrgCache to obtain random strings.
        
        The RandomOrgCache can be polled for new results conforming to 
        the output format of the input request. See output of 
        generate_strings() for the return value of a poll on 
        RandomOrgCache.
        
        Keyword arguments:
        
        n -- How many random strings you need. Must be within the 
            [1,1e4] range.
        length -- The length of each string. Must be within the [1,20] 
            range. All strings will be of the same length.
        characters -- A string that contains the set of characters that
            are allowed to occur in the random strings. The maximum 
            number of characters is 80.
        replacement -- Specifies whether the random strings should be 
            picked with replacement. If True the resulting list of 
            strings may contain duplicates, otherwise the strings will 
            all be unique (default True).
        cache_size -- Number of result-sets for the cache to try to 
            maintain at any given time (default 20, minimum 2).
        """
        
        if cache_size < 2:
            cache_size = 2
        
        # if possible, make requests more efficient by bulk-ordering 
        # from the server. Either 5 sets of items at a time, or 
        # cache_size/2 if 5 >= cache_size.
        if replacement:
            bulk_n = cache_size//2 if 5 >= cache_size else 5
            params = { 'apiKey':self._api_key, 'n':bulk_n*n, 'length':length, 
                       'characters':characters, 'replacement':replacement }
        
        # not possible to make the request more efficient
        else:
            bulk_n = 0
            params = { 'apiKey':self._api_key, 'n':n, 'length':length, 
                       'characters':characters, 'replacement':replacement }
        
        # get the request object for use in all requests from this cache
        request = self._generate_request(_STRING_METHOD, params)
        
        return RandomOrgCache(self._send_request, self._extract_strings, 
                              request, cache_size, bulk_n, n)
    
    def create_UUID_cache(self, n, cache_size=10):
        """
        Get a RandomOrgCache to obtain random UUIDs.
        
        The RandomOrgCache can be polled for new results conforming to 
        the output format of the input request. See output of 
        generate_UUIDs() for the return value of a poll on 
        RandomOrgCache.
        
        Keyword arguments:
        
        n -- How many random UUIDs you need. Must be within the [1,1e3]
            range.
        cache_size -- Number of result-sets for the cache to try to 
            maintain at any given time (default 10, minimum 2).
        """
        
        if cache_size < 2:
            cache_size = 2
        
        # make requests more efficient by bulk-ordering 
        # from the server. Either 5 sets of items at a time, or 
        # cache_size/2 if 5 >= cache_size.
        bulk_n = cache_size//2 if 5 >= cache_size else 5
        params = { 'apiKey':self._api_key, 'n':bulk_n*n }
                
        # get the request object for use in all requests from this cache
        request = self._generate_request(_UUID_METHOD, params)
        
        return RandomOrgCache(self._send_request, self._extract_UUIDs, 
                              request, cache_size, bulk_n, n)
    
    def create_blob_cache(self, n, size, format=_BLOB_FORMAT_BASE64, 
                          cache_size=10):
        """
        Get a RandomOrgCache to obtain random blobs.
        
        The RandomOrgCache can be polled for new results conforming to 
        the output format of the input request. See output of 
        generate_blobs() for the return value of a poll on 
        RandomOrgCache.
        
        Keyword arguments:
        
        n -- How many random blobs you need. Must be within the [1,100]
            range.
        size -- The size of each blob, measured in bits. Must be within
            the [1,1048576] range and must be divisible by 8.
        format -- Specifies the format in which the blobs will be 
            returned. Values allowed are _BLOB_FORMAT_BASE64 and 
            _BLOB_FORMAT_HEX (default _BLOB_FORMAT_BASE64).
        cache_size -- Number of result-sets for the cache to try to 
            maintain at any given time (default 10, minimum 2).
        """
        
        if cache_size < 2:
            cache_size = 2
        
        # make requests more efficient by bulk-ordering 
        # from the server. Either 5 sets of items at a time, or 
        # cache_size/2 if 5 >= cache_size.
        bulk_n = cache_size//2 if 5 >= cache_size else 5
        params = { 'apiKey':self._api_key, 'n':bulk_n*n, 'size':size, 
                  'format':format }
        
        # get the request object for use in all requests from this cache
        request = self._generate_request(_BLOB_METHOD, params)
        
        return RandomOrgCache(self._send_request, self._extract_blobs, 
                              request, cache_size, bulk_n, n)
    
    
    # Methods for accessing server usage statistics
    
    def get_requests_left(self):
        """
        Get remaining requests.
        
        Return the (estimated) number of remaining API requests 
        available to the client. If cached usage info is older than 
        _ALLOWANCE_STATE_REFRESH_SECONDS fresh info is obtained from 
        server. If fresh info has to be obtained the following 
        exceptions can be raised.
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped. 
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        """
        try:
            # Python 2.7
            if self._requests_left is None or \
               time.clock() > (self._last_response_received_time 
                               + _ALLOWANCE_STATE_REFRESH_SECONDS):
                self._get_usage()
        except AttributeError:
            # Python 3.3+
            if self._requests_left is None or \
               time.process_time() > (self._last_response_received_time 
                                      + _ALLOWANCE_STATE_REFRESH_SECONDS):
                self._get_usage()
        return self._requests_left
    
    def get_bits_left(self):
        """
        Get remaining bits.
        
        Return the (estimated) number of remaining true random bits 
        available to the client. If cached usage info is older than 
        _ALLOWANCE_STATE_REFRESH_SECONDS fresh info is obtained from 
        server. If fresh info has to be obtained the following 
        exceptions can be raised.
        
        Raises a RandomOrgSendTimeoutError if time spent waiting before
        request is sent exceeds this instance's blocking_timeout.
        
        Raises a RandomOrgKeyNonExistentError if this API key does not 
        exist.
        
        Raises a RandomOrgKeyNotRunningError if this API key is stopped. 
        
        Raises a RandomOrgInsufficientRequestsError if this API key's 
        server requests allowance has been exceeded and the instance is
        backing off until midnight UTC.
        
        Raises a RandomOrgInsufficientBitsError if this API key's 
        server bits allowance has been exceeded.
        
        Raises a ValueError on RANDOM.ORG Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Raises a RuntimeError on JSON-RPC Errors, error descriptions:
        https://api.random.org/json-rpc/4/error-codes
        
        Can also raise connection errors as described here:
        http://docs.python-requests.org/en/v2.0-0/user/quickstart/#errors-and-exceptions
        """
        try:
            # Python 2.7
            if self._bits_left is None or \
            time.clock() > (self._last_response_received_time 
                                   + _ALLOWANCE_STATE_REFRESH_SECONDS):
                self._get_usage()
        except AttributeError:
            # Python 3.3+
            if self._bits_left is None or \
            time.process_time() > (self._last_response_received_time 
                                   + _ALLOWANCE_STATE_REFRESH_SECONDS):
                self._get_usage()            
        return self._bits_left
    
    
    # Private methods for class operation.
    
    def _send_unserialized_request(self, request):
        # Send request immediately.
        data = self._send_request_core(request)
        
        # Raise any thrown exceptions.
        if 'exception' in data:
            raise data['exception']
        
        # Return response.
        return data['response']
    
    def _send_serialized_request(self, request):
        # Add request to the queue with it's own Condition lock.
        lock = threading.Condition()
        lock.acquire()
        
        data = {'lock': lock, 'request': request, 'response': None, 
                'exception': None}
        self._serialized_queue.put(data)
        
        # Wait on the Condition for the specified blocking timeout.
        lock.wait(timeout=None if self._blocking_timeout == -1 
                  else self._blocking_timeout)
        
        # Lock has now either been notified or timed out.
        # Examine data to determine which and react accordingly.
        
        # Request wasn't sent in time, cancel and raise exception.
        if data['response'] is None and data['exception'] is None:
            data['request'] = None
            lock.release()
            raise RandomOrgSendTimeoutError('The defined maximum \
                                            allowed blocking time of ' 
                                            + str(self._blocking_timeout) 
                                            + 's has been exceeded while \
                                            waiting for a synchronous \
                                            request to send.')
        
        # Exception on sending request.
        if data['exception'] is not None:
            lock.release()
            raise data['exception']
        
        # Request was successful.
        lock.release()
        return data['response']
    
    def _threaded_request_sending(self):
        # Thread to execute queued requests.
        while True:
            # Block and wait for a request.
            request = self._serialized_queue.get(block=True)
            
            # Get the request's lock to indicate request in progress.
            lock = request['lock']
            lock.acquire()
            
            # If request still exists it hasn't been cancelled.
            if request['request'] is not None:
                # Send request.
                data = self._send_request_core(request['request'])
                # Set result.
                if 'exception' in data:
                    request['exception'] = data['exception']
                else:
                    request['response'] = data['response']
            
            # Notify completion and return
            lock.notify()
            lock.release()
    
    def _send_request_core(self, request):
        # If a backoff is set, no more requests can be issued until the
        # required backoff time is up.
        if self._backoff is not None:
            # Time not yet up, throw exception.
            if datetime.utcnow() < self._backoff:
                return { 'exception': 
                        RandomOrgInsufficientRequestsError(self._backoff_error) }
            
            # Time is up, clear backoff.
            else:
                self._backoff = None
                self._backoff_error = None
        
        # Check server advisory delay.
        self._advisory_delay_lock.acquire()
        try:
            # Python 2.7
            wait = self._advisory_delay - (time.clock() 
                                           - self._last_response_received_time)
        except AttributeError:
            # Python 3.3+
            wait = self._advisory_delay - (time.process_time() 
                                           - self._last_response_received_time)
        self._advisory_delay_lock.release()
        
        # Wait the specified delay if necessary and if wait time is not
        # longer than the set blocking_timeout.
        if wait > 0:
            if (self._blocking_timeout != -1 and wait > self._blocking_timeout):
                return { 'exception': 
                        RandomOrgSendTimeoutError('The server advisory delay of ' 
                                                  + str(wait) + 's is greater than \
                                                  the defined maximum allowed \
                                                  blocking time of ' 
                                                  + str(self._blocking_timeout) + 's.') }
            time.sleep(wait)
        
        # Send the request & parse the response.
        response = requests.post('https://api.random.org/json-rpc/4/invoke',
                                 data=json.dumps(request), 
                                 headers={'content-type': 'application/json'},
                                 timeout=self._http_timeout)
        data = response.json()
        
        if 'error' in data:
            code = int(data['error']['code'])
            message = data['error']['message']
            
            # RuntimeError, error codes listed under JSON-RPC Errors:
            # https://api.random.org/json-rpc/4/error-codes
            if code in ([-32700] + list(range(-32603,-32600)) 
                        + list(range(-32099,-32000))):                
                return { 'exception': RuntimeError('Error ' + str(code) 
                                                   + ': ' + message) }
            
            # RandomOrgKeyNonExistentError, API key does not exist, from 
            # RANDOM.ORG Errors: https://api.random.org/json-rpc/4/error-codes
            elif code == 400:
                return { 'exception': 
                        RandomOrgKeyNonExistentError('Error ' + str(code) 
                                                    + ': ' + message) }
            
            # RandomOrgKeyNotRunningError, API key not running, from 
            # RANDOM.ORG Errors: https://api.random.org/json-rpc/4/error-codes
            elif code == 401:
                return { 'exception': 
                        RandomOrgKeyNotRunningError('Error ' + str(code) 
                                                    + ': ' + message) }
                
            # RandomOrgInsufficientRequestsError, requests allowance 
            # exceeded, backoff until midnight UTC, from RANDOM.ORG 
            # Errors: https://api.random.org/json-rpc/4/error-codes
            elif code == 402:
                self._backoff = datetime.utcnow().replace(day=datetime.utcnow().day+1, hour=0, 
                                                          minute=0, second=0, microsecond=0)
                self._backoff_error = 'Error ' + str(code) + ': ' + message
                return { 'exception': 
                        RandomOrgInsufficientRequestsError(self._backoff_error) }
            
            # RandomOrgInsufficientBitsError, bits allowance exceeded,
            # from RANDOM.ORG Errors: https://api.random.org/json-rpc/4/error-codes
            elif code == 403:
                return { 'exception': 
                        RandomOrgInsufficientBitsError('Error ' + str(code) 
                                                       + ': ' + message) }
            
            # RandomOrgKeyInvalidAccessError, key is not valid for method 
            # requested, from RANDOM.ORG Errors: 
            # https://api.random.org/json-rpc/4/error-codes
            elif code == 404:
                return { 'exception':
                        RandomOrgKeyInvalidAccessError('Error ' + str(code) 
                                                       + ': ' + message) }
            
            # RandomOrgKeyInvalidVersionError, key is not valid for the 
            # version of the API you are invoking, from RANDOM.ORG Errors: 
            # https://api.random.org/json-rpc/4/error-codes
            elif code == 405:
                return { 'exception':
                        RandomOrgKeyInvalidVersionError('Error' + str(code) 
                                                        + ': ' + message)}
            
            # RandomOrgTicketNonExistentError, the ticket specified does
            # not exist, from RANDOM.ORG Errors: 
            # https://api.random.org/json-rpc/4/error-codes 
            elif code == 420:
                return { 'exception':
                        RandomOrgTicketNonExistentError('Error' + str(code) 
                                                        + ': ' + message)}
            
            # RandomOrgTicketAPIKeyMismatchError, the ticket specified 
            # exists but is not for the API key you specified, 
            # from RANDOM.ORG Errors: 
            # https://api.random.org/json-rpc/4/error-codes
            elif code == 421:
                return { 'exception':
                        RandomOrgTicketAPIKeyMismatchError('Error' + str(code) 
                                                           + ': ' + message)}
            
            # RandomOrgTicketAlreadyUsedError, the ticket specified has 
            # already been used, from RANDOM.ORG Errors: 
            # https://api.random.org/json-rpc/4/error-codes
            elif code == 422:
                return { 'exception':
                        RandomOrgTicketAlreadyUsedError('Error' + str(code) 
                                                        + ': ' + message)}
            
            # RandomOrgTooManySingletonTicketsError, the maximum number 
            # of singleton tickets available for your API key has been 
            # reached, from RANDOM.ORG Errors: 
            # https://api.random.org/json-rpc/4/error-codes
            elif code == 423:
                return { 'exception':
                        RandomOrgTooManySingletonTicketsError('Error' 
                                                              + str(code) 
                                                              + ': '
                                                              + message)}
    
            # RandomOrgLicenseDataRequiredError, your API key requires the 
            # license_data parameter be used, from RANDOM.ORG Errors:
            # https://api.random.org/json-rpc/4/error-codes
            elif code == 424:
                return { 'exception':
                        RandomOrgLicenseDataRequiredError('Error' 
                                                          + str(code) 
                                                          + ': ' + message)}
            
            # RandomOrgLicenseDataNotAllowedError, your API key does not 
            # support the use of the license_data parameter, 
            # from RANDOM.ORG Errors: 
            # https://api.random.org/json-rpc/4/error-codes
            elif code == 425:
                return { 'exception':
                        RandomOrgLicenseDataNotAllowedError('Error' 
                                                            + str(code) 
                                                            + ': ' 
                                                            + message)}
             
            # ValueError, error codes listed under RANDOM.ORG Errors:
            # https://api.random.org/json-rpc/4/error-codes
            else:
                return { 'exception': ValueError('Error ' + str(code) 
                                                 + ': ' + message) }
        
        # Update usage stats
        if 'requestsLeft' in data['result']:
            self._requests_left = int(data['result']['requestsLeft'])
            self._bits_left = int(data['result']['bitsLeft'])
        
        # Set new server advisory delay
        self._advisory_delay_lock.acquire()
        if 'advisoryDelay' in data['result']:
            # Convert millis to decimal seconds.
            if sys.version_info[0] < 3.0:
                # Python 2.7
                self._advisory_delay = (long(data['result']['advisoryDelay']) 
                                        / 1000.0)
            else:
                # Python 3+
                self._advisory_delay = (int(data['result']['advisoryDelay']) 
                                        / 1000.0)
        else:
            # Use default if none from server.
            self._advisory_delay = _DEFAULT_DELAY
        
        try:
            # Python 2.7
            self._last_response_received_time = time.clock()
        except AttributeError: 
            # Python 3.3+
            self._last_response_received_time = time.process_time()
        
        self._advisory_delay_lock.release()
        
        return { 'response': data }
    
    def _get_usage(self):
        # Issue a getUsage request to update bits and requests left.
        params = { 'apiKey':self._api_key }
        request = self._generate_request(_GET_USAGE_METHOD, params)
        response = self._send_request(request)
    
    def _generate_request(self, method, params):
        # Base json request.
        return { 'jsonrpc':'2.0', 'method':method, 'params':params, 
                'id':uuid.uuid4().hex }
    
    def _extract_response(self, response):
        # Gets random data.
        return response['result']['random']['data']
    
    def _extract_signed_response(self, response, extract_function, 
                                 decimal=True):
        # Gets all random data and signature.
        if decimal:
            return { 'data':extract_function(response), 
                    'random':response['result']['random'], 
                    'signature':response['result']['signature'] }
        else: 
            return { 'data':extract_function(response, decimal),
                    'random':response['result']['random'], 
                    'signature':response['result']['signature']}
        
    def _extract_verification_response(self, response):
        # Gets verification boolean.
        return bool(response['result']['authenticity'])
    
    def _extract_tickets(self, response):
        # Gets list of tickets for create_tickets method
        return response['result']
    
    def _extract_ints(self, response, decimal=True):
        # json to integer list.
        if decimal:
            return list(map(int, self._extract_response(response)))
        else:
            return self._extract_response(response)
    
    def _extract_int_sequences(self, response, decimal=True):
        # json to integer sequences list.
        if decimal:
            return [list(map(int, rest)) for rest in 
                    self._extract_response(response)]
        else: 
            return [list(rest) for rest 
                    in self._extract_response(response)]
        
    def _extract_doubles(self, response):
        # json to double list.
        return list(map(float, self._extract_response(response)))
    
    def _extract_strings(self, response):
        # json to string list (no change).
        return self._extract_response(response)
    
    def _extract_UUIDs(self, response):
        # json to UUID list.
        return list(map(uuid.UUID, self._extract_response(response)))
    
    def _extract_blobs(self, response):
        # json to blob list (no change).
        return self._extract_response(response)
    
    def _url_formatting(self, s):
        # adjust the formatting of elements used in url
        if isinstance(s, dict):
           s = json.dumps(s, separators=(',', ':'))
        
        # check if the string is base64 encoded
        b64_pattern = '^([A-Za-z0-9+/]{4})*([A-Za-z0-9+/]{3}=|[A-Za-z0-9+/]{2}==)?$'
        is_b64 = re.search(b64_pattern, s)
        
        if not is_b64:
           s = s.encode()
           s = base64.b64encode(s)
           s = s.decode()
    
        # replace certain characters to make them url-safe
        # (Percent-Encoding as described in RFC 3986 for PHP)
        s = s.replace('=', '%3D')
        s = s.replace('+', '%2B')
        s = s.replace('/', '%2F')
    
        # return formatted string
        return s
    
    def _input_html(self, type, name, value):
        # helper function to create html code with input tags
        return ('<input type=\'' + str(type) + '\' name=\'' + str(name)
                + '\' value=\'' + str(value) + '\' />')
