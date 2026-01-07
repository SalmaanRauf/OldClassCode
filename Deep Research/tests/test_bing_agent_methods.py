"""
Unit tests for Bing Data Extraction Agent enhanced methods.

This module tests the new general research methods that were added to
the BingDataExtractionAgent class to ensure they are properly accessible
and functional.
"""
import pytest
from unittest.mock import Mock, patch
from agents.bing_data_extraction_agent import BingDataExtractionAgent


class TestBingAgentMethods:
    """Test class for Bing agent enhanced methods."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        # Mock the Azure credentials and environment variables
        with patch.dict('os.environ', {
            'PROJECT_ENDPOINT': 'https://test-endpoint.com',
            'MODEL_DEPLOYMENT_NAME': 'test-model',
            'AZURE_BING_CONNECTION_ID': 'test-connection-id'
        }):
            with patch('azure.identity.DefaultAzureCredential'):
                self.agent = BingDataExtractionAgent()
    
    def test_agent_initialization(self):
        """Test that the agent initializes properly with new methods."""
        # Verify the agent has all the new methods
        assert hasattr(self.agent, 'search_market_overview')
        assert hasattr(self.agent, 'search_industry_analysis')
        assert hasattr(self.agent, 'search_regulatory_updates')
        assert hasattr(self.agent, 'search_competitor_analysis')
        assert hasattr(self.agent, 'search_general_topic')
        assert hasattr(self.agent, 'search_company_any')
        assert hasattr(self.agent, 'search_financial_companies_by_location')
        assert hasattr(self.agent, 'search_technology_trends')
        assert hasattr(self.agent, 'search_market_rankings')
    
    @patch.object(BingDataExtractionAgent, '_run_agent_task')
    def test_search_market_overview(self, mock_run_task):
        """Test search_market_overview method."""
        # Mock the return value
        mock_run_task.return_value = {
            'summary': 'Test market overview',
            'citations_md': '- [Test Source](https://test.com)',
            'audit': {'citation_count': 1, 'search_queries': ['test query']}
        }
        
        # Test the method
        result = self.agent.search_market_overview('financial services', 'USA', 10)
        
        # Verify the method was called with correct parameters
        mock_run_task.assert_called_once()
        call_args = mock_run_task.call_args[0][0]
        assert 'Top 10 financial services companies' in call_args
        assert 'in USA' in call_args
        assert 'market size revenue ranking' in call_args
        
        # Verify the result
        assert result['summary'] == 'Test market overview'
        assert result['citations_md'] == '- [Test Source](https://test.com)'
    
    @patch.object(BingDataExtractionAgent, '_run_agent_task')
    def test_search_industry_analysis(self, mock_run_task):
        """Test search_industry_analysis method."""
        mock_run_task.return_value = {
            'summary': 'Test industry analysis',
            'citations_md': '- [Industry Report](https://test.com)',
            'audit': {'citation_count': 1, 'search_queries': ['test query']}
        }
        
        result = self.agent.search_industry_analysis('technology', 'USA')
        
        mock_run_task.assert_called_once()
        call_args = mock_run_task.call_args[0][0]
        assert 'technology industry analysis' in call_args
        assert 'USA' in call_args
        assert 'trends market outlook' in call_args
        
        assert result['summary'] == 'Test industry analysis'
    
    @patch.object(BingDataExtractionAgent, '_run_agent_task')
    def test_search_regulatory_updates(self, mock_run_task):
        """Test search_regulatory_updates method."""
        mock_run_task.return_value = {
            'summary': 'Test regulatory updates',
            'citations_md': '- [Regulatory News](https://test.com)',
            'audit': {'citation_count': 1, 'search_queries': ['test query']}
        }
        
        result = self.agent.search_regulatory_updates('fintech', 'USA')
        
        mock_run_task.assert_called_once()
        call_args = mock_run_task.call_args[0][0]
        assert 'fintech regulatory updates' in call_args
        assert 'USA' in call_args
        assert 'new regulations 2024 2025' in call_args
        
        assert result['summary'] == 'Test regulatory updates'
    
    @patch.object(BingDataExtractionAgent, '_run_agent_task')
    def test_search_competitor_analysis(self, mock_run_task):
        """Test search_competitor_analysis method."""
        mock_run_task.return_value = {
            'summary': 'Test competitor analysis',
            'citations_md': '- [Competitor Report](https://test.com)',
            'audit': {'citation_count': 1, 'search_queries': ['test query']}
        }
        
        result = self.agent.search_competitor_analysis('Apple')
        
        mock_run_task.assert_called_once()
        call_args = mock_run_task.call_args[0][0]
        assert 'Top competitors of Apple' in call_args
        assert 'market share analysis' in call_args
        assert 'competitive landscape' in call_args
        
        assert result['summary'] == 'Test competitor analysis'
    
    @patch.object(BingDataExtractionAgent, '_run_agent_task')
    def test_search_general_topic(self, mock_run_task):
        """Test search_general_topic method."""
        mock_run_task.return_value = {
            'summary': 'Test general topic',
            'citations_md': '- [General Source](https://test.com)',
            'audit': {'citation_count': 1, 'search_queries': ['test query']}
        }
        
        result = self.agent.search_general_topic('artificial intelligence trends')
        
        mock_run_task.assert_called_once()
        call_args = mock_run_task.call_args[0][0]
        assert 'artificial intelligence trends' in call_args
        assert 'analysis overview recent developments' in call_args
        assert '2024 2025' in call_args
        
        assert result['summary'] == 'Test general topic'
    
    @patch.object(BingDataExtractionAgent, '_run_agent_task')
    def test_search_company_any(self, mock_run_task):
        """Test search_company_any method."""
        mock_run_task.return_value = {
            'summary': 'Test company analysis',
            'citations_md': '- [Company Info](https://test.com)',
            'audit': {'citation_count': 1, 'search_queries': ['test query']}
        }
        
        result = self.agent.search_company_any('Tesla')
        
        mock_run_task.assert_called_once()
        call_args = mock_run_task.call_args[0][0]
        assert 'Tesla company overview' in call_args
        assert 'business model financial performance' in call_args
        assert 'recent news 2024 2025' in call_args
        
        assert result['summary'] == 'Test company analysis'
    
    @patch.object(BingDataExtractionAgent, '_run_agent_task')
    def test_search_financial_companies_by_location(self, mock_run_task):
        """Test search_financial_companies_by_location method."""
        mock_run_task.return_value = {
            'summary': 'Test financial companies',
            'citations_md': '- [Financial Report](https://test.com)',
            'audit': {'citation_count': 1, 'search_queries': ['test query']}
        }
        
        result = self.agent.search_financial_companies_by_location('Puerto Rico', 30)
        
        mock_run_task.assert_called_once()
        call_args = mock_run_task.call_args[0][0]
        assert 'Top 30 financial companies banks' in call_args
        assert 'in Puerto Rico' in call_args
        assert 'market size revenue ranking' in call_args
        
        assert result['summary'] == 'Test financial companies'
    
    @patch.object(BingDataExtractionAgent, '_run_agent_task')
    def test_search_technology_trends(self, mock_run_task):
        """Test search_technology_trends method."""
        mock_run_task.return_value = {
            'summary': 'Test technology trends',
            'citations_md': '- [Tech Report](https://test.com)',
            'audit': {'citation_count': 1, 'search_queries': ['test query']}
        }
        
        result = self.agent.search_technology_trends('healthcare')
        
        mock_run_task.assert_called_once()
        call_args = mock_run_task.call_args[0][0]
        assert 'Technology trends innovations' in call_args
        assert 'in healthcare' in call_args
        assert 'AI digital transformation' in call_args
        
        assert result['summary'] == 'Test technology trends'
    
    @patch.object(BingDataExtractionAgent, '_run_agent_task')
    def test_search_market_rankings(self, mock_run_task):
        """Test search_market_rankings method."""
        mock_run_task.return_value = {
            'summary': 'Test market rankings',
            'citations_md': '- [Ranking Report](https://test.com)',
            'audit': {'citation_count': 1, 'search_queries': ['test query']}
        }
        
        result = self.agent.search_market_rankings('banks', 'USA', 20)
        
        mock_run_task.assert_called_once()
        call_args = mock_run_task.call_args[0][0]
        assert 'Top 20 banks ranking' in call_args
        assert 'in USA' in call_args
        assert 'market share revenue' in call_args
        
        assert result['summary'] == 'Test market rankings'


if __name__ == "__main__":
    pytest.main([__file__])
