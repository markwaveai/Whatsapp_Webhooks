
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add parent directory to path so we can import main
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock elasticsearch module BEFORE importing main to avoid connection attempts during import
# This is crucial because main.py initializes the ES client at the top level
sys.modules['elasticsearch'] = MagicMock()

import main

class TestGetChatName(unittest.TestCase):
    def setUp(self):
        # Reset mocks before each test
        # Since main.es was created at import time (and is a Mock), we reset it
        main.es = MagicMock()
        
        # Ensure API keys are set for tests (can be overridden in specific tests)
        main.PERISKOPE_API_KEY = "test_key"
        main.PERISKOPE_ORG_PHONE = "test_phone"
        main.PERISKOPE_API_BASE_URL = "https://api.test.com/"
        main.CACHE_INDEX = "test_cache_index"

    def test_cache_hit(self):
        """
        Scenario: Chat name is found in Elasticsearch cache.
        Expected: Return cached name, no API call.
        """
        # Setup cache returning a document
        main.es.get.return_value = {
            'found': True,
            '_source': {'chat_name': 'Cached Team Alpha'}
        }
        
        with patch('requests.get') as mock_requests:
            result = main.get_chat_name('chat_123')
            
            self.assertEqual(result, 'Cached Team Alpha')
            
            # Verify ES get was called
            main.es.get.assert_called_with(index='test_cache_index', id='chat_123', ignore=[404])
            
            # Verify API was NOT called
            mock_requests.assert_not_called()

    def test_cache_miss_api_success(self):
        """
        Scenario: Chat name not in cache, API call succeeds.
        Expected: Return API name, fetch members, and update cache.
        """
        # Setup cache miss (first call for chat, and subsequent calls for members)
        main.es.get.side_effect = lambda index, id, ignore: {'found': False}
        
        # Setup API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'chat_name': 'API Team Beta',
            'members': {
                'user_1': {'contact_name': 'Alice'},
                'user_2': {'contact_name': 'Bob'}
            }
        }
        
        with patch('requests.get', return_value=mock_response) as mock_requests:
            result = main.get_chat_name('chat_456')
            
            self.assertEqual(result, 'API Team Beta')
            
            # Verify API call
            mock_requests.assert_called_once()
            self.assertIn('chat/chat_456', mock_requests.call_args[0][0])
            
            # Verify caching happened
            # We expect caching for the main chat AND the 2 members
            # Total 3 index calls
            self.assertEqual(main.es.index.call_count, 3)
            
            # Verify chat name was cached
            # Extract all calls to index
            calls = main.es.index.call_args_list
            cached_documents = [call.kwargs['document'] for call in calls]
            
            # Check for main chat
            chat_doc = next((d for d in cached_documents if d['chat_id'] == 'chat_456'), None)
            self.assertIsNotNone(chat_doc)
            self.assertEqual(chat_doc['chat_name'], 'API Team Beta')
            
            # Check for members
            member_doc = next((d for d in cached_documents if d['chat_id'] == 'user_1'), None)
            self.assertIsNotNone(member_doc)
            self.assertEqual(member_doc['chat_name'], 'Alice')

    def test_api_failure(self):
        """
        Scenario: Cache miss and API returns 404 or other error.
        Expected: Return chat_id as fallback.
        """
        main.es.get.return_value = {'found': False}
        
        mock_response = MagicMock()
        mock_response.status_code = 404
        
        with patch('requests.get', return_value=mock_response):
            result = main.get_chat_name('unknown_chat')
            self.assertEqual(result, 'unknown_chat')

    def test_missing_credentials(self):
        """
        Scenario: API credentials are missing.
        Expected: Return chat_id immediately without API call.
        """
        main.es.get.return_value = {'found': False}
        main.PERISKOPE_API_KEY = None
        
        with patch('requests.get') as mock_requests:
            result = main.get_chat_name('chat_789')
            self.assertEqual(result, 'chat_789')
            mock_requests.assert_not_called()

    def test_api_exception(self):
        """
        Scenario: API call raises an exception.
        Expected: Return chat_id fallback.
        """
        main.es.get.return_value = {'found': False}
        
        with patch('requests.get', side_effect=Exception("Network error")):
            result = main.get_chat_name('chat_error')
            self.assertEqual(result, 'chat_error')

if __name__ == '__main__':
    unittest.main()
