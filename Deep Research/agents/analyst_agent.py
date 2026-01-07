"""
Analyst Agent - Semantic Kernel-powered analysis functions.

This module provides the main analyst agent that uses Semantic Kernel
functions for various analysis tasks including intent resolution.
"""
import json
import asyncio
import re
import os
import logging
from typing import List, Dict, Any, Optional, Tuple
from config.kernel_setup import get_kernel, get_kernel_async
from semantic_kernel.functions import KernelFunctionFromPrompt
from semantic_kernel.kernel import KernelArguments
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents.text_content import TextContent
from dataclasses import dataclass
import traceback
from pathlib import Path
from semantic_kernel.functions.kernel_arguments import KernelArguments

logger = logging.getLogger(__name__)

class AnalystAgent:
    def __init__(self, chunk_size: int = 3000, chunk_overlap: int = 500, max_chunks: int = 10):
        try:
            self.kernel, self.exec_settings = get_kernel()
        except RuntimeError:
            self.kernel = None
            self.exec_settings = None
        self.functions = {}
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_chunks = max_chunks
        self.company_profiles = {}
        self._load_functions()
        
    def set_profiles(self, profiles_dict: dict):
        normalized = {}
        for key, profile in (profiles_dict or {}).items():
            if not profile:
                continue
            canonical = profile.get("company_name") or key
            variants = {
                key,
                canonical,
                (key or "").lower(),
                (canonical or "").lower(),
            }
            for variant in variants:
                if variant:
                    normalized[variant] = profile
        self.company_profiles = normalized

    async def _ensure_kernel_initialized(self):
        if self.kernel is None or self.exec_settings is None:
            self.kernel, self.exec_settings = await get_kernel_async()
            self._load_functions()

    def _lookup_company_profile(self, company: str):
        if not company:
            return {}
        return (
            self.company_profiles.get(company)
            or self.company_profiles.get(company.lower())
            or self.company_profiles.get(company.replace("_", " "))
            or self.company_profiles.get(company.replace("_", " ").lower())
            or {}
        )

    async def ensure_kernel_ready(self) -> None:
        """Public helper to guarantee kernel and SK functions are available."""
        await self._ensure_kernel_initialized()
        
    def _load_functions(self):
        # Always resolve relative to the project root
        project_root = Path(__file__).parent.parent
        sk_dir = project_root / "sk_functions"
        
        prompt_files = {
            "triage": "Triage_CategoryRouting_prompt.txt",
            "financial": "FinancialEvent_Detection_prompt.txt", 
            "procurement": "OpportunityIdent_skprompt.txt",
            "earnings": "EarningsCall_GuidanceAnalysis_prompt.txt",
            "insight": "StrategicInsight_Generation_prompt.txt",
            "company_takeaway": "CompanyTakeaway_skprompt.txt",
            "intent_resolver": "Intent_Resolver_prompt.txt",  # Add intent resolver
        }
        for name, fname in prompt_files.items():
            path = sk_dir / fname
            try:
                with open(path, "r", encoding="utf-8") as f:
                    template = f.read()
                plugin_name = "analyst_plugin" if name != "intent_resolver" else "intent_plugin"
                func = KernelFunctionFromPrompt(
                    function_name=name,
                    plugin_name=plugin_name,
                    description=f"{name} analysis function",
                    prompt=template
                )
                self.functions[name] = func
                if self.kernel:
                    try:
                        self.kernel.add_function(function=func, plugin_name=plugin_name)
                        logger.debug("Successfully loaded SK function '%s'", name)
                    except Exception as ex:
                        logger.warning("Failed to add SK function '%s': %s", name, ex)
            except FileNotFoundError:
                logger.error("Prompt file not found: %s", path)
            except Exception as e:
                logger.exception("Error loading prompt '%s' from %s", name, path)
        logger.info("Loaded %d Semantic Kernel functions", len(self.functions))

    async def _invoke_function_safely(self, function_name: str, input_text: str):
        try:
            if function_name not in self.functions:
                raise ValueError(f"Function '{function_name}' not found")
            func = self.functions[function_name]
            arguments = KernelArguments(input=input_text)
            prompt_template = getattr(func, "prompt", None)
            if prompt_template:
                try:
                    if logger.isEnabledFor(logging.DEBUG):
                        debug_prompt = prompt_template.replace("{{$input}}", input_text)
                        snippet = debug_prompt if len(debug_prompt) <= 800 else debug_prompt[:800] + "..."
                        logger.debug("Prompt for SK function '%s': %s", function_name, snippet)
                except Exception as e:
                    logger.debug("Could not render debug prompt for '%s': %s", function_name, e)
            result = await self.kernel.invoke(
                function_name=function_name,
                plugin_name="analyst_plugin" if function_name != "intent_resolver" else "intent_plugin",
                arguments=arguments
            )
            return result
        except Exception as e:
            logger.exception("Error invoking function '%s'", function_name)
            return None

    # Include all the existing methods from the original analyst agent
    def _create_intelligent_chunks(self, text: str, chunk_size: int = None, overlap: int = None) -> List[str]:
        if not text:
            return []
        if len(text) > 10_000_000:
            print(f"⚠️  Text too large ({len(text)} chars), truncating to 10MB")
            text = text[:10_000_000]
        chunk_size = chunk_size or self.chunk_size
        overlap = overlap or self.chunk_overlap
        if len(text) <= chunk_size:
            return [text]
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            initial_memory = process.memory_info().rss
        except ImportError:
            process = None
            initial_memory = 0
        chunks = []
        start = 0
        while start < len(text) and len(chunks) < self.max_chunks:
            if process and len(chunks) % 10 == 0:
                current_memory = process.memory_info().rss
                if current_memory - initial_memory > 500_000_000:
                    print("⚠️  Memory usage too high, stopping chunk creation")
                    break
            end = start + chunk_size
            if end < len(text):
                search_start = max(start + chunk_size - 200, start)
                search_end = min(start + chunk_size + 200, len(text))
                best_break = end
                for i in range(search_start, search_end):
                    if text[i] in '.!?':
                        if i + 1 < len(text) and text[i + 1] in ' \n\t':
                            if i + 2 < len(text) and text[i + 2].isupper():
                                best_break = i + 1
                                break
                end = best_break
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - overlap
            if start >= len(text):
                break
        return chunks

    def _extract_key_terms(self, text: str) -> List[str]:
        key_patterns = [
            r'\$\s*[0-9,.]+(?:\s*(?:million|billion|thousand|m|bn|k))?',
            r'\b(?:Capital One|Fannie Mae|Freddie Mac|Navy Federal|PenFed|EagleBank|Capital Bank)\b',
            r'\b(?:investment|acquisition|merger|partnership|funding|contract|deal|agreement)\b',
            r'\b(?:announces|launches|completes|signs|reports|discloses)\b'
        ]
        key_terms = []
        for pattern in key_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            key_terms.extend(matches)
        return list(set(key_terms))

    def _prioritize_chunks(self, chunks: List[str]) -> List[str]:
        if not chunks:
            return []
        chunk_scores = []
        for i, chunk in enumerate(chunks):
            score = 0
            key_terms = self._extract_key_terms(chunk)
            score += len(key_terms) * 10
            if re.search(r'\$\s*[0-9,.]+', chunk):
                score += 50
            if re.search(r'\b(?:Capital One|Fannie Mae|Freddie Mac|Navy Federal|PenFed|EagleBank|Capital Bank)\b', chunk, re.IGNORECASE):
                score += 30
            if re.search(r'\b(?:announces|launches|completes|signs|reports|discloses)\b', chunk, re.IGNORECASE):
                score += 20
            chunk_scores.append((score, i, chunk))
        chunk_scores.sort(reverse=True)
        return [chunk for _, _, chunk in chunk_scores]

    async def _analyze_chunks_with_map_reduce(self, chunks: List[str], analysis_function: str, max_chunks: int = None) -> List[Dict[str, Any]]:
        if not chunks:
            return []
        max_chunks = max_chunks or self.max_chunks
        prioritized_chunks = self._prioritize_chunks(chunks)[:max_chunks]
        print(f"🔍 Analyzing {len(prioritized_chunks)} prioritized chunks (from {len(chunks)} total)")
        tasks = []
        for i, chunk in enumerate(prioritized_chunks):
            tasks.append(self._analyze_single_chunk(i, chunk, analysis_function))
        chunk_results = []
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"❌ Task {i} failed: {result}")
                elif result:
                    chunk_results.append(result)
        except Exception as e:
            print(f"❌ Gather operation failed: {e}")
        return self._synthesize_chunk_results(chunk_results, analysis_function)

    async def _analyze_single_chunk(self, i: int, chunk: str, analysis_function: str) -> Optional[Dict[str, Any]]:
        try:
            result = await self._invoke_function_safely(analysis_function, chunk)
            if result is None:
                return None
            parsed_result = self._safe_json_parse(result, f"chunk_analysis_{analysis_function}")
            if not parsed_result:
                return None
            if parsed_result.get('event_found', False) or parsed_result.get('is_relevant', False):
                return {
                    'chunk_index': i,
                    'chunk_text': chunk[:200] + "..." if len(chunk) > 200 else chunk,
                    'result': parsed_result,
                    'key_terms': self._extract_key_terms(chunk)
                }
        except Exception as e:
            print(f"⚠️  Error analyzing chunk {i}: {e}")
        return None

    def _synthesize_chunk_results(self, chunk_results: List[Dict[str, Any]], analysis_type: str) -> List[Dict[str, Any]]:
        if not chunk_results:
            return []
        if analysis_type in ['procurement', 'earnings']:
            return [result['result'] for result in chunk_results if result['result'].get('event_found', False)]
        else:
            return [chunk_results[0]['result']] if chunk_results else []

    def _safe_json_parse(self, result, context="unknown") -> Optional[Dict]:
        import re
        try:
            from semantic_kernel.functions.function_result import FunctionResult
        except ImportError:
            FunctionResult = None
        if FunctionResult and isinstance(result, FunctionResult):
            result = result.value
        if isinstance(result, list):
            for entry in result:
                parsed = self._safe_json_parse(entry, context)
                if parsed is not None:
                    return parsed
            return None
        if hasattr(result, "content") and isinstance(result.content, str):
            content = result.content
        elif hasattr(result, "inner_content"):
            inner_result = result.inner_content
            if hasattr(inner_result, "choices") and hasattr(inner_result.choices[0], "message") and hasattr(inner_result.choices[0].message, "content"):
                content = inner_result.choices[0].message.content
            elif hasattr(inner_result, "content"):
                content = inner_result.content
            else:
                content = str(inner_result)
        elif hasattr(result, "choices") and hasattr(result.choices[0], "message") and hasattr(result.choices[0].message, "content"):
            content = result.choices[0].message.content
        elif hasattr(result, "value"):
            content = str(result.value)
        elif isinstance(result, str):
            content = result
        else:
            content = str(result)
        if not content:
            print(f"⚠️  Empty content for JSON parsing in {context}")
            return None
        content = content.strip()
        if content.startswith('```json'):
            content = content[len('```json'):].strip()
        if content.startswith('```'):
            content = content[len('```'):].strip()
        if content.endswith('```'):
            content = content[:-3].strip()
        content = re.sub(r'^(json|CopyEdit|Edit)?\\s*', '', content)
        try:
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                print(f"❌ JSON is not a dictionary in {context}")
                return None
            return parsed
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error in {context}: {e}")
            print(f"📋 Problematic content: {content[:500]}...")
            return None
        except Exception as e:
            print(f"❌ Unexpected error parsing JSON in {context}: {e}")
            return None

    @staticmethod
    def _json_safe(value):
        """Recursively convert Semantic Kernel payloads into JSON-serializable structures."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [AnalystAgent._json_safe(v) for v in value]
        if isinstance(value, dict):
            return {k: AnalystAgent._json_safe(v) for k, v in value.items()}
        if hasattr(value, "dict"):
            return AnalystAgent._json_safe(value.dict())
        if hasattr(value, "model_dump"):
            return AnalystAgent._json_safe(value.model_dump())
        return str(value)

    # Include all other existing methods from the original analyst agent
    async def analyze_consolidated_data(self, events_input, analysis_document: str) -> List[Dict[str, Any]]:
        if isinstance(events_input, dict) and "events" in events_input and "profiles" in events_input:
            events = events_input["events"]
            profiles = events_input["profiles"]
        else:
            events = events_input
            profiles = getattr(self, "company_profiles", {})
        self.set_profiles(profiles)
        print(f"🧠 Starting analysis of {len(events)} consolidated items...")
        adapted_data = []
        for item in events:
            raw_data = item.get('raw_data', {})
            adapted_item = {
                'title': item.get('title', raw_data.get('title', '')),
                'description': item.get('content', item.get('description', raw_data.get('description', ''))),
                'company': item.get('company', raw_data.get('company', '')),
                'source': item.get('source_name', raw_data.get('source', '')),
                'url': item.get('url', raw_data.get('link', '')),
                'published_date': item.get('published_date', raw_data.get('date', '')),
                'source_type': item.get('source_type', 'unknown'),
                'key_terms': item.get('key_terms', []),
                'relevance_score': item.get('relevance_score', 0.0)
            }
            source = adapted_item['source'].lower()
            if 'sec' in source:
                adapted_item['type'] = 'news'
                adapted_item['data_type'] = 'filing'
            elif 'sam.gov' in source:
                adapted_item['type'] = 'procurement'
            elif 'news' in source:
                adapted_item['type'] = 'news'
            else:
                adapted_item['type'] = 'unknown'
            if isinstance(raw_data, dict) and 'value_usd' in raw_data:
                adapted_item['value_usd'] = raw_data['value_usd']
            if adapted_item['type'] == 'news':
                adapted_item['summary'] = adapted_item['description']
            elif adapted_item.get('data_type') == 'filing':
                adapted_item['text'] = f"{adapted_item['title']} {adapted_item['description']}"
            adapted_data.append(adapted_item)
        print(f"✅ Adapted {len(adapted_data)} items for analysis")
        results = await self.analyze_all_data(adapted_data)
        print(f"🎯 Analysis complete: {len(results)} events identified")
        return results
    
    async def triage_data(self, data_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        await self._ensure_kernel_initialized()
        relevant_items = []
        
        if not isinstance(self.chunk_size, int):
            print(f"⚠️  WARNING: chunk_size is {type(self.chunk_size)}, resetting to 3000")
            self.chunk_size = 3000
        
        for item in data_items:
            try:
                text = item.get('content') or item.get('description') or ''
                if not text:
                    continue
                if len(text) <= self.chunk_size:
                    result = await self._invoke_function_safely('triage', text)
                    if result is None:
                        continue
                    triage_result = self._safe_json_parse(result, "triage")
                    if triage_result and triage_result.get('is_relevant', False):
                        item['triage'] = triage_result
                        relevant_items.append(item)
                else:
                    chunks = self._create_intelligent_chunks(text)
                    chunk_triage = []
                    for ch in chunks:
                        result = await self._invoke_function_safely('triage', ch)
                        tri = self._safe_json_parse(result, "triage") if result else None
                        if tri and tri.get('is_relevant', False):
                            chunk_triage.append(tri)
                    if chunk_triage:
                        item['triage'] = chunk_triage[0]
                        relevant_items.append(item)
            except Exception as e:
                print(f"Error during triage: {e}")
                continue
        print(f"Triage complete: {len(relevant_items)} relevant items found")
        return relevant_items

    async def analyze_financial_events(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        await self._ensure_kernel_initialized()
        financial_events = []
        for item in items:
            try:
                text = item.get('content') or item.get('description') or ''
                if not text:
                    continue
                if len(text) <= self.chunk_size:
                    result = await self._invoke_function_safely('financial', text)
                    if result is None:
                        continue
                    financial_result = self._safe_json_parse(result, "financial_analysis")
                    if financial_result and financial_result.get('event_found', False):
                        item['financial_analysis'] = financial_result
                        financial_events.append(item)
                else:
                    chunks = self._create_intelligent_chunks(text)
                    chunk_results = await self._analyze_chunks_with_map_reduce(chunks, 'financial')
                    if chunk_results:
                        synthesized = chunk_results[0]
                        if synthesized.get('event_found', False):
                            item['financial_analysis'] = synthesized
                            item['analysis_metadata'] = {
                                'chunks_analyzed': len(chunks),
                                'analysis_method': 'map_reduce'
                            }
                            financial_events.append(item)
            except Exception as e:
                print(f"Error during financial event analysis: {e}")
                continue
        print(f"Financial event analysis complete: {len(financial_events)} events found")
        return financial_events

    async def analyze_procurement(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        await self._ensure_kernel_initialized()
        procurement_events = []
        for item in items:
            try:
                text = item.get('content') or item.get('description') or ''
                if not text:
                    continue
                result = await self._invoke_function_safely('procurement', text)
                if result is None:
                    continue
                procurement_result = self._safe_json_parse(result, "procurement_analysis")
                if procurement_result and procurement_result.get('is_relevant', False):
                    item['procurement_analysis'] = procurement_result
                    procurement_events.append(item)
            except Exception as e:
                print(f"Error during procurement analysis: {e}")
                continue
        print(f"Procurement analysis complete: {len(procurement_events)} opportunities found")
        return procurement_events

    async def analyze_earnings_calls(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        await self._ensure_kernel_initialized()
        earnings_events = []
        for item in items:
            try:
                text = item.get('content') or item.get('description') or ''
                if not text:
                    continue
                if len(text) <= self.chunk_size:
                    result = await self._invoke_function_safely('earnings', text)
                    if result is None:
                        continue
                    earnings_result = self._safe_json_parse(result, "earnings_analysis")
                    if earnings_result and earnings_result.get('guidance_found', False):
                        value_usd = earnings_result.get('value_usd', 0)
                        item['earnings_analysis'] = earnings_result
                        earnings_events.append(item)
                else:
                    chunks = self._create_intelligent_chunks(text)
                    chunk_results = await self._analyze_chunks_with_map_reduce(chunks, 'earnings')
                    if chunk_results:
                        synthesized = chunk_results[0]
                        if synthesized.get('guidance_found', False):
                            value_usd = synthesized.get('value_usd', 0)
                            item['earnings_analysis'] = synthesized
                            item['analysis_metadata'] = {
                                'chunks_analyzed': len(chunks),
                                'analysis_method': 'map_reduce'
                            }
                            earnings_events.append(item)
            except Exception as e:
                print(f"Error during earnings call analysis: {e}")
                continue
        print(f"Earnings call analysis complete: {len(earnings_events)} guidance items found")
        return earnings_events

    async def generate_insights(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        await self._ensure_kernel_initialized()
        insights = []
        for event in events:
            try:
                company_profile = self._lookup_company_profile(event.get('company', ''))
                insight_data = {
                    'company': event.get('company', ''),
                    'title': event.get('title', ''),
                    'source': event.get('source', ''),
                    'type': event.get('type', ''),
                    'company_profile': company_profile,
                    'key_buyers': company_profile.get('key_buyers', []),
                    'projects': company_profile.get('projects', []),
                    'protiviti_alumni': company_profile.get('protiviti_alumni', []),
                    'citations': event.get('citations', []),
                }
                if 'financial_analysis' in event:
                    insight_data.update(event['financial_analysis'])
                elif 'procurement_analysis' in event:
                    insight_data.update(event['procurement_analysis'])
                elif 'earnings_analysis' in event:
                    insight_data.update(event['earnings_analysis'])
                insight_payload = self._json_safe(insight_data)
                event['citations'] = self._json_safe(event.get('citations', []))
                result = await self._invoke_function_safely('insight', json.dumps(insight_payload))
                if result is None:
                    continue
                insight_result = self._safe_json_parse(result, "insight_generation")
                if insight_result:
                    event['insights'] = insight_result
                    insights.append(event)
                else:
                    print(f"Warning: Could not parse insight for event: {event.get('title', 'Unknown')}")
            except Exception as e:
                print(f"Error generating insight: {e}")
                continue
        from collections import defaultdict
        company_map = defaultdict(list)
        for ev in insights:
            company_map[ev['company']].append(ev)
        for company, evts in company_map.items():
            profile = self._lookup_company_profile(company)
            summary_input = {
                'company': company,
                'profile': profile,
                'events': [{
                    'title': e['title'], 'insights': e.get('insights', {})
                } for e in evts]
            }
            summary_json = json.dumps(self._json_safe(summary_input))
            summary = await self._invoke_function_safely('company_takeaway', summary_json)
            for e in evts:
                e['company_takeaway'] = summary
        print(f"Insight generation complete: {len(insights)} insights generated")
        return insights

    async def analyze_all_data(self, data_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        print(f"Starting analysis of {len(data_items)} data items...")
        relevant_items = await self.triage_data(data_items)
        financial_events = await self.analyze_financial_events(relevant_items)
        procurement_events = await self.analyze_procurement(relevant_items)
        earnings_events = await self.analyze_earnings_calls(relevant_items)

        scoped_priority = [
            "sec_filings",
            "news",
            "procurement",
            "earnings",
            "industry_context",
        ]

        deduped_by_scope: Dict[Tuple[str, str], Dict[str, Any]] = {}
        fallback_events: List[Dict[str, Any]] = []
        for event in financial_events + procurement_events + earnings_events:
            if not isinstance(event, dict):
                fallback_events.append(event)
                continue
            company = event.get('company')
            raw_data = event.get('raw_data') or {}
            scope = raw_data.get('scope') if isinstance(raw_data, dict) else None
            if company and scope:
                key = (company, scope)
                if key not in deduped_by_scope:
                    deduped_by_scope[key] = event
            else:
                fallback_events.append(event)

        ordered_events: List[Dict[str, Any]] = []
        for scope in scoped_priority:
            for (company, scoped), event in deduped_by_scope.items():
                if scoped == scope:
                    ordered_events.append(event)
        for (company, scoped), event in deduped_by_scope.items():
            if scoped not in scoped_priority:
                ordered_events.append(event)
        ordered_events.extend(fallback_events)

        final_insights = await self.generate_insights(ordered_events)
        print(f"Analysis complete: {len(final_insights)} high-impact events identified")
        return final_insights
