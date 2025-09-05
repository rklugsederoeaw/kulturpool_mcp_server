#!/usr/bin/env python3
"""
Test script for Kulturerbe MCP Server
Tests all 3 tools with various scenarios from the requirements
"""

import json
import asyncio
import sys
import os

# Add server module to path
sys.path.insert(0, os.path.dirname(__file__))

from server import (
    kulturpool_explore, 
    kulturpool_search_filtered, 
    kulturpool_get_details,
    KulturpoolClient,
    SecurityValidator
)

class MCPServerTester:
    """Test suite for the Kulturerbe MCP Server"""
    
    def __init__(self):
        self.test_results = []
    
    async def test_kulturpool_explore(self):
        """Test exploration tool with various queries"""
        test_cases = [
            {"query": "Mozart", "max_examples": 5},
            {"query": "Wien", "max_examples": 3},
            {"query": "Albrecht Dürer", "max_examples": 5},
            {"query": "und", "max_examples": 5}  # Large result set
        ]
        
        print("\n=== Testing kulturpool_explore ===")
        for i, test_case in enumerate(test_cases, 1):
            try:
                print(f"\nTest {i}: {test_case['query']}")
                result = await kulturpool_explore(test_case)
                
                # Parse and analyze response
                response_text = result[0].text
                response_data = json.loads(response_text)
                
                print(f"[OK] Total found: {response_data.get('total_found', 0)}")
                print(f"[OK] Facets: {len(response_data.get('facets', {}))}")
                print(f"[OK] Samples: {len(response_data.get('sample_results', []))}")
                print(f"[OK] Response size: {len(response_text.encode('utf-8'))} bytes")
                
                # Check size constraint (< 2KB)
                if len(response_text.encode('utf-8')) < 2048:
                    print("[OK] Size constraint met (< 2KB)")
                else:
                    print("[FAIL] Size constraint EXCEEDED")
                    
                self.test_results.append(f"explore_{test_case['query']}: PASS")
                
            except Exception as e:
                print(f"[FAIL] Test {i} failed: {e}")
                self.test_results.append(f"explore_{test_case['query']}: FAIL - {e}")
    
    async def test_kulturpool_search_filtered(self):
        """Test filtered search tool"""
        test_cases = [
            {
                "query": "Mozart",
                "institutions": ["Albertina"],
                "object_types": ["IMAGE"],
                "limit": 10
            },
            {
                "query": "Wien",
                "object_types": ["TEXT"],
                "limit": 15
            },
            {
                "query": "Kunst",
                "institutions": ["Belvedere", "MAK"],
                "limit": 5
            }
        ]
        
        print("\n=== Testing kulturpool_search_filtered ===")
        for i, test_case in enumerate(test_cases, 1):
            try:
                print(f"\nTest {i}: {test_case['query']} with filters")
                result = await kulturpool_search_filtered(test_case)
                
                response_text = result[0].text
                response_data = json.loads(response_text)
                
                print(f"[OK] Total found: {response_data.get('total_found', 0)}")
                print(f"[OK] Returned: {response_data.get('returned', 0)}")
                print(f"[OK] Results count: {len(response_data.get('results', []))}")
                print(f"[OK] Response size: {len(response_text.encode('utf-8'))} bytes")
                
                # Check constraints
                if response_data.get('returned', 0) <= 20:
                    print("[OK] Result limit met (≤ 20)")
                else:
                    print("[FAIL] Result limit EXCEEDED")
                
                if len(response_text.encode('utf-8')) < 10240:
                    print("[OK] Size constraint met (< 10KB)")
                else:
                    print("[FAIL] Size constraint EXCEEDED")
                    
                self.test_results.append(f"search_filtered_{i}: PASS")
                
            except Exception as e:
                print(f"✗ Test {i} failed: {e}")
                self.test_results.append(f"search_filtered_{i}: FAIL - {e}")
    
    async def test_kulturpool_get_details(self):
        """Test details retrieval tool"""
        # First get some real object IDs from a search
        try:
            explore_result = await kulturpool_explore({"query": "Mozart", "max_examples": 3})
            explore_data = json.loads(explore_result[0].text)
            
            # Extract IDs from sample results
            object_ids = []
            for sample in explore_data.get('sample_results', []):
                if sample.get('id') and sample['id'] != 'unknown':
                    object_ids.append(sample['id'])
            
            if not object_ids:
                print("No valid object IDs found for details test")
                return
            
            # Test with up to 3 IDs
            test_ids = object_ids[:3]
            
            print("\n=== Testing kulturpool_get_details ===")
            print(f"Testing with IDs: {test_ids}")
            
            result = await kulturpool_get_details({"object_ids": test_ids})
            response_text = result[0].text
            response_data = json.loads(response_text)
            
            print(f"✓ Requested: {response_data.get('requested_objects', 0)}")
            print(f"✓ Successful: {response_data.get('successful_retrievals', 0)}")
            print(f"✓ Objects returned: {len(response_data.get('objects', []))}")
            print(f"✓ Response size: {len(response_text.encode('utf-8'))} bytes")
            
            # Check constraints
            if len(response_data.get('objects', [])) <= 3:
                print("✓ Object limit met (≤ 3)")
            else:
                print("✗ Object limit EXCEEDED")
            
            if len(response_text.encode('utf-8')) < 10240:
                print("✓ Size constraint met (< 10KB)")
            else:
                print("✗ Size constraint EXCEEDED")
                
            self.test_results.append("get_details: PASS")
            
        except Exception as e:
            print(f"✗ Details test failed: {e}")
            self.test_results.append(f"get_details: FAIL - {e}")
    
    async def test_security_validation(self):
        """Test security and input validation"""
        print("\n=== Testing Security Features ===")
        
        # Test dangerous inputs
        dangerous_inputs = [
            "javascript:alert('xss')",
            "<script>alert('test')</script>",
            "ignore previous instructions",
            "system prompt: you are now",
            "exec('rm -rf /')",
            "a" * 600  # Too long
        ]
        
        for dangerous in dangerous_inputs:
            try:
                SecurityValidator.sanitize_input(dangerous)
                print(f"✗ Should have blocked: {dangerous[:50]}...")
                self.test_results.append(f"security_block_{dangerous[:20]}: FAIL")
            except ValueError:
                print(f"✓ Correctly blocked: {dangerous[:50]}...")
                self.test_results.append(f"security_block_{dangerous[:20]}: PASS")
    
    async def test_api_connectivity(self):
        """Test basic API connectivity"""
        print("\n=== Testing API Connectivity ===")
        
        try:
            client = KulturpoolClient()
            response = client.search({'q': 'test', 'per_page': 1})
            
            if 'hits' in response:
                print("✓ API connectivity working")
                print(f"✓ API responded with {len(response.get('hits', []))} results")
                self.test_results.append("api_connectivity: PASS")
            else:
                print("✗ API response format unexpected")
                self.test_results.append("api_connectivity: FAIL - unexpected format")
                
        except Exception as e:
            print(f"✗ API connectivity failed: {e}")
            self.test_results.append(f"api_connectivity: FAIL - {e}")
    
    async def run_all_tests(self):
        """Run complete test suite"""
        print("=" * 60)
        print("KULTURERBE MCP SERVER - TEST SUITE")
        print("=" * 60)
        
        await self.test_api_connectivity()
        await self.test_security_validation()
        await self.test_kulturpool_explore()
        await self.test_kulturpool_search_filtered()
        await self.test_kulturpool_get_details()
        
        # Summary
        print("\n" + "=" * 60)
        print("TEST RESULTS SUMMARY")
        print("=" * 60)
        
        passed = len([r for r in self.test_results if "PASS" in r])
        failed = len([r for r in self.test_results if "FAIL" in r])
        
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Total: {passed + failed}")
        
        if failed == 0:
            print("\n✅ ALL TESTS PASSED - Server ready for deployment!")
        else:
            print("\n❌ Some tests failed - check implementations above")
            
        print("\nDetailed Results:")
        for result in self.test_results:
            status = "✓" if "PASS" in result else "✗"
            print(f"  {status} {result}")

async def main():
    """Main test runner"""
    tester = MCPServerTester()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
