#!/usr/bin/env python3
"""
Boston.com Speed Read - News Summary Generator
Fetches Boston.com RSS feeds and creates concise, non-clickbait summaries
"""

import json
import os
import sys
import time
import random
from datetime import datetime, timezone
from typing import List, Dict, Optional

import feedparser
import requests
from openai import OpenAI
from bs4 import BeautifulSoup

# Configuration
RSS_FEEDS = [
    "https://www.boston.com/feed/bdc-msn-rss"
]

MAX_ARTICLES = 12
OPENAI_MODEL = "gpt-4"
REQUEST_TIMEOUT = 30
RETRY_ATTEMPTS = 3

class BostonNewsGenerator:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; BostonSpeedRead/1.0)'
        })
        
    def fetch_article_content(self, url: str) -> Optional[str]:
        """Extract article text from URL"""
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove unwanted elements
            for element in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                element.decompose()
            
            # Try to find article content
            content = None
            for selector in ['.entry-content', '.article-body', '.post-content', 'article']:
                element = soup.select_one(selector)
                if element:
                    content = element.get_text(strip=True)
                    break
            
            if not content:
                # Fallback to all paragraphs
                paragraphs = soup.find_all('p')
                content = ' '.join([p.get_text(strip=True) for p in paragraphs[:10]])
            
            return content[:4000] if content else None
            
        except Exception as e:
            print(f"Error fetching article content from {url}: {e}")
            return None
    
    def create_summary(self, title: str, content: str, url: str) -> List[str]:
        """Generate 3-bullet summary using OpenAI"""
        
        # Analyze content to create story-specific curiosity gaps
        prompt = f"""You are creating a 3-bullet summary for a Boston news story. 

STORY TITLE: {title}
STORY CONTENT: {content[:2000]}

Create exactly 3 bullets following these rules:

BULLET 1: What happened - concrete facts, include specific numbers/names if available
BULLET 2: Key detail or impact - why this matters to Boston/locals  
BULLET 3: Story-specific curiosity gap - identify something genuinely intriguing about THIS specific story that would make someone want to read more. DO NOT use generic phrases like "You won't believe", "The surprising reason", "One detail changes everything", etc. Instead, hint at specific unanswered questions, contradictions, backstories, or unexpected connections that are unique to this particular story.

Examples of GOOD bullet 3s (story-specific):
- "The restaurant's sudden closure traces back to a decades-old family feud"  
- "Three city councilors changed their votes in the final 30 seconds"
- "The building's architect designed it to intentionally violate fire codes"
- "Police found evidence that contradicts the victim's own testimony"

Examples of BAD bullet 3s (generic templates):
- "You won't believe what happened next"
- "The surprising reason will shock you" 
- "One detail changes everything"
- "The truth behind X will amaze you"

Be specific to THIS story. What unique, substantive detail or question would genuinely intrigue readers?

Format as three separate lines, each starting with a bullet point."""

        try:
            response = self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are an expert at creating concise, factual news summaries that avoid clickbait while still being compelling."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.7
            )
            
            summary_text = response.choices[0].message.content.strip()
            
            # Parse bullets
            bullets = []
            for line in summary_text.split('\n'):
                line = line.strip()
                if line and any(line.startswith(prefix) for prefix in ['•', '-', '*', '1.', '2.', '3.']):
                    # Clean up bullet formatting
                    clean_line = line
                    for prefix in ['•', '-', '*', '1.', '2.', '3.']:
                        if clean_line.startswith(prefix):
                            clean_line = clean_line[len(prefix):].strip()
                            break
                    bullets.append(clean_line)
            
            # Ensure we have exactly 3 bullets
            if len(bullets) >= 3:
                return bullets[:3]
            else:
                # Fallback if parsing failed
                return [
                    f"Breaking news from Boston: {title}",
                    "Story developing with local impact",
                    f"Full details and context available at Boston.com"
                ]
                
        except Exception as e:
            print(f"Error generating summary for {title}: {e}")
            return [
                f"Boston news update: {title}",
                "Local story with community impact", 
                "Additional details in full article"
            ]
    
    def determine_hook_type(self, title: str, content: str) -> str:
        """Determine the story type/hook"""
        title_lower = title.lower()
        content_lower = content.lower() if content else ""
        
        if any(word in title_lower for word in ['patriots', 'celtics', 'bruins', 'red sox']):
            return "SPORTS"
        elif any(word in title_lower for word in ['mbta', 'orange line', 'green line', 'commuter rail', 'traffic']):
            return "TRANSIT"
        elif any(word in title_lower for word in ['mayor', 'city council', 'election', 'vote']):
            return "POLITICS"
        elif any(word in title_lower for word in ['weather', 'storm', 'snow', 'rain']):
            return "WEATHER"
        elif any(word in content_lower for word in ['boston', 'cambridge', 'somerville', 'brookline']):
            return "LOCAL_IMPACT"
        else:
            return "NEWS"
    
    def fetch_and_process_feeds(self) -> List[Dict]:
        """Fetch articles from RSS feeds and process them"""
        all_articles = []
        seen_urls = set()
        
        for feed_url in RSS_FEEDS:
            try:
                print(f"Fetching feed: {feed_url}")
                feed = feedparser.parse(feed_url)
                
                for entry in feed.entries[:15]:  # Get more from the main feed
                    if entry.link in seen_urls:
                        continue
                    
                    seen_urls.add(entry.link)
                    
                    # Get article content
                    content = self.fetch_article_content(entry.link)
                    if not content:
                        content = entry.get('summary', '')
                    
                    # Create summary
                    summary = self.create_summary(entry.title, content, entry.link)
                    hook_type = self.determine_hook_type(entry.title, content)
                    
                    article = {
                        "title": entry.title,
                        "link": entry.link,
                        "pubDate": entry.get('published', ''),
                        "summary": summary,
                        "hookType": hook_type,
                        "processed_at": datetime.now(timezone.utc).isoformat()
                    }
                    
                    all_articles.append(article)
                    print(f"Processed: {entry.title[:60]}...")
                    
                    # Add small delay to be respectful
                    time.sleep(1)
                    
            except Exception as e:
                print(f"Error processing feed {feed_url}: {e}")
                continue
        
        # Sort by publication date and limit
        all_articles.sort(key=lambda x: x.get('pubDate', ''), reverse=True)
        return all_articles[:MAX_ARTICLES]
    
    def save_data(self, articles: List[Dict]):
        """Save processed articles to JSON files"""
        current_time = datetime.now(timezone.utc).isoformat()
        
        # Current data for the website
        news_data = {
            "lastUpdated": current_time,
            "articles": articles,
            "stats": {
                "totalArticles": len(articles),
                "lastRefresh": current_time,
                "version": "2.0"
            }
        }
        
        with open("news-data.json", "w", encoding="utf-8") as f:
            json.dump(news_data, f, indent=2, ensure_ascii=False)
        
        # Load existing history
        try:
            with open("news-history.json", "r", encoding="utf-8") as f:
                history = json.load(f)
        except FileNotFoundError:
            history = {"articles": [], "totalArticles": 0}
        
        # Add new articles to history (avoid duplicates)
        existing_links = {article["link"] for article in history.get("articles", [])}
        new_articles = [article for article in articles if article["link"] not in existing_links]
        
        history["articles"] = new_articles + history.get("articles", [])
        history["articles"] = history["articles"][:50]  # Keep last 50
        history["lastUpdated"] = current_time
        history["totalArticles"] = len(history["articles"])
        
        with open("news-history.json", "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        
        print(f"Saved {len(articles)} articles ({len(new_articles)} new)")

def main():
    """Main execution function"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set")
        sys.exit(1)
