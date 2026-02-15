from flask import Flask, request, jsonify
from flask_cors import CORS
import fitz  # PyMuPDF
import zipfile
import io
import re
from pathlib import Path
import json
import tempfile
import os
from collections import defaultdict

app = Flask(__name__)
CORS(app, origins="*", allow_headers="*", methods="*")

class ConceptExtractor:
    """Extract key concepts and topics from text"""
    
    TECH_KEYWORDS = {
        'assembly': ['assembly', 'assembler', 'asm', 'x86', 'x64', 'instruction', 'opcode'],
        'performance': ['optimization', 'performance', 'speed', 'cache', 'register', 'cycle'],
        'memory': ['memory', 'ram', 'address', 'pointer', 'heap', 'stack', 'segment'],
        'optimization': ['optimize', 'efficient', 'fast', 'slow', 'overhead', 'latency'],
        'hardware': ['cpu', 'processor', 'gpu', 'core', 'bus', 'bandwidth'],
        'machine_code': ['machine code', 'bytecode', 'binary', 'hex', 'encoding'],
        'debugging': ['debug', 'breakpoint', 'trace', 'analyze', 'profil'],
        'algorithm': ['algorithm', 'complexity', 'recursive', 'loop', 'iterate'],
        'system': ['system', 'kernel', 'interrupt', 'io', 'device', 'driver'],
    }
    
    @staticmethod
    def extract_concepts(text, limit=5):
        """Extract main concepts from text"""
        text_lower = text.lower()
        found_concepts = {}
        
        for concept_name, keywords in ConceptExtractor.TECH_KEYWORDS.items():
            count = sum(text_lower.count(kw) for kw in keywords)
            if count > 0:
                found_concepts[concept_name] = count
        
        # Return top concepts
        sorted_concepts = sorted(found_concepts.items(), key=lambda x: x[1], reverse=True)
        return [c[0] for c in sorted_concepts[:limit]]
    
    @staticmethod
    def extract_key_quotes(text, limit=3):
        """Extract important sentences as potential quotes"""
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 50 and len(s.strip()) < 200]
        
        # Score sentences by presence of important keywords
        scored = []
        important_words = ['important', 'key', 'critical', 'essential', 'must', 'always', 'never', 'optimal']
        
        for sent in sentences:
            score = sum(1 for word in important_words if word in sent.lower())
            if score > 0 or any(keyword in sent.lower() for keywords in ConceptExtractor.TECH_KEYWORDS.values() for keyword in keywords):
                scored.append((sent, score))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in scored[:limit]]
    
    @staticmethod
    def calculate_importance(text):
        """Calculate importance level (high, medium, low)"""
        important_indicators = ['critical', 'essential', 'important', 'must', 'key', 'fundamental']
        
        count = sum(text.lower().count(word) for word in important_indicators)
        
        if count >= 3:
            return 'high'
        elif count >= 1:
            return 'medium'
        else:
            return 'low'


class ChapterDetector:
    """Detect chapter boundaries and structure"""
    
    @staticmethod
    def detect_chapters(text, page_markers):
        """Detect chapter boundaries from text"""
        lines = text.split('\n')
        chapters = []
        current_chapter = None
        chapter_num = 0
        
        chapter_patterns = [
            r'^chapter\s+(\d+)[:\s]',
            r'^(\d+)\.\s+([A-Z][^:]+):',
            r'^(?:Chapter|CHAPTER)\s+(\w+)',
        ]
        
        for line_num, line in enumerate(lines):
            line_stripped = line.strip()
            
            for pattern in chapter_patterns:
                if re.match(pattern, line_stripped, re.IGNORECASE):
                    if current_chapter:
                        chapters.append(current_chapter)
                    
                    chapter_num += 1
                    current_chapter = {
                        'num': chapter_num,
                        'title': line_stripped,
                        'start_line': line_num,
                        'sections': []
                    }
                    break
        
        if current_chapter:
            chapters.append(current_chapter)
        
        return chapters if chapters else [{'num': 1, 'title': 'Main Content', 'start_line': 0, 'sections': []}]


class PDFExtractor:
    def __init__(self):
        self.markers = 0
        self.images = []
        self.concepts = []
        self.chapters = []
        
    def extract_pdf(self, file_path):
        """Extract text with enhanced structure from PDF"""
        try:
            doc = fitz.open(file_path)
            full_text = ""
            self.markers = 0
            self.images = []
            
            # Get metadata
            metadata = doc.metadata
            page_count = doc.page_count
            
            for page_num, page in enumerate(doc, 1):
                # Extract text with layout
                text = page.get_text("text")
                
                # Detect headings (larger text)
                blocks = page.get_text("blocks")
                headings = self._extract_headings(blocks)
                
                # Detect images
                image_list = page.get_images()
                if image_list:
                    full_text += f"[IMAGE]: {len(image_list)} image(s) on page {page_num}\n"
                    self.markers += 1
                    self.images.extend([(page_num, len(image_list))])
                
                if text.strip():
                    full_text += f"[SECTION]: Page {page_num}\n"
                    if headings:
                        full_text += f"[HEADING]: {headings[0]}\n"
                        self.markers += 1
                    full_text += text + "\n\n"
                    self.markers += 1
            
            # Extract concepts from full text
            self.concepts = ConceptExtractor.extract_concepts(full_text)
            
            # Detect chapters
            self.chapters = ChapterDetector.detect_chapters(full_text, [])
            
            doc.close()
            
            return {
                'text': full_text.strip(),
                'metadata': {
                    'title': metadata.get('title', 'Unknown') if metadata else 'Unknown',
                    'author': metadata.get('author', 'Unknown') if metadata else 'Unknown',
                    'pages': page_count,
                    'creation_date': metadata.get('creationDate', 'N/A') if metadata else 'N/A'
                },
                'markers': self.markers,
                'images_found': len(self.images),
                'concepts': self.concepts,
                'chapters': len(self.chapters)
            }
        except Exception as e:
            return {'error': str(e)}
    
    def _extract_headings(self, blocks):
        """Extract potential headings from text blocks"""
        headings = []
        for block in blocks:
            if len(block) > 4 and isinstance(block[4], str):
                text = block[4].strip()
                if len(text) < 100 and len(text) > 5:
                    headings.append(text)
        return headings[:1]


class OutputFormatter:
    """Generate multiple output formats optimized for different uses"""
    
    @staticmethod
    def generate_enhanced_txt(text, metadata, concepts):
        """Generate enhanced TXT with metadata markers for Claude"""
        output = ""
        
        # Header
        output += f"[TITLE]: {metadata.get('title', 'Unknown')}\n"
        output += f"[AUTHOR]: {metadata.get('author', 'Unknown')}\n"
        output += f"[PAGES]: {metadata.get('pages', 'Unknown')}\n"
        output += f"[CONCEPTS]: {', '.join(concepts)}\n"
        output += f"[FORMAT]: Enhanced for AI Processing\n"
        output += "=" * 80 + "\n\n"
        
        # Process sections
        section_blocks = re.split(r'\[SECTION\]:', text)
        
        for idx, section in enumerate(section_blocks[1:], 1):
            lines = section.split('\n')
            
            if lines:
                # Parse page number and heading
                page_match = re.match(r'\s*Page (\d+)', lines[0])
                page_num = int(page_match.group(1)) if page_match else idx
                
                heading = ""
                content_start = 1
                
                if len(lines) > 1 and '[HEADING]' in lines[1]:
                    heading = lines[1].replace('[HEADING]:', '').strip()
                    content_start = 2
                
                # Extract concepts from this section
                section_text = '\n'.join(lines[content_start:])
                section_concepts = ConceptExtractor.extract_concepts(section_text, limit=3)
                
                # Extract key quotes
                key_quotes = ConceptExtractor.extract_key_quotes(section_text, limit=2)
                
                # Calculate importance
                importance = ConceptExtractor.calculate_importance(section_text)
                
                # Write enhanced section
                output += f"[SECTION_ID]: {idx}\n"
                output += f"[PAGE]: {page_num}\n"
                output += f"[HEADING]: {heading}\n"
                output += f"[CONCEPTS]: {', '.join(section_concepts)}\n"
                output += f"[IMPORTANCE]: {importance}\n"
                
                if key_quotes:
                    output += f"[KEY_QUOTES]: {len(key_quotes)}\n"
                    for quote in key_quotes:
                        output += f"  - {quote[:100]}...\n"
                
                output += "\n"
                output += section_text + "\n"
                output += "-" * 80 + "\n\n"
        
        return output
    
    @staticmethod
    def generate_structured_json(text, metadata, concepts):
        """Generate structured JSON for semantic search and Claude reference"""
        sections = []
        section_blocks = re.split(r'\[SECTION\]:', text)
        
        for idx, block in enumerate(section_blocks[1:], 1):
            lines = block.split('\n')
            
            if lines:
                page_match = re.match(r'\s*Page (\d+)', lines[0])
                page_num = int(page_match.group(1)) if page_match else idx
                
                heading = ""
                content_start = 1
                
                if len(lines) > 1 and '[HEADING]' in lines[1]:
                    heading = lines[1].replace('[HEADING]:', '').strip()
                    content_start = 2
                
                content = '\n'.join(lines[content_start:]).strip()
                
                # Extract metadata for this section
                section_concepts = ConceptExtractor.extract_concepts(content, limit=3)
                key_quotes = ConceptExtractor.extract_key_quotes(content, limit=2)
                importance = ConceptExtractor.calculate_importance(content)
                
                section_obj = {
                    "section_id": idx,
                    "page": page_num,
                    "heading": heading,
                    "content": content,
                    "metadata": {
                        "concepts": section_concepts,
                        "topics": concepts,
                        "importance": importance,
                        "key_quotes": key_quotes,
                        "word_count": len(content.split())
                    }
                }
                sections.append(section_obj)
        
        return {
            "book_metadata": {
                "title": metadata.get('title', 'Unknown'),
                "author": metadata.get('author', 'Unknown'),
                "pages": metadata.get('pages', 0),
                "total_sections": len(sections),
                "concepts": concepts,
                "creation_date": metadata.get('creation_date', 'N/A')
            },
            "sections": sections
        }
    
    @staticmethod
    def generate_jsonl(text, metadata, concepts):
        """Generate JSONL for fine-tuning with enhanced metadata"""
        lines = []
        section_blocks = re.split(r'\[SECTION\]:', text)
        
        for idx, block in enumerate(section_blocks[1:], 1):
            block_lines = block.split('\n')
            
            if block_lines:
                page_match = re.match(r'\s*Page (\d+)', block_lines[0])
                page_num = int(page_match.group(1)) if page_match else idx
                
                heading = ""
                content_start = 1
                
                if len(block_lines) > 1 and '[HEADING]' in block_lines[1]:
                    heading = block_lines[1].replace('[HEADING]:', '').strip()
                    content_start = 2
                
                content = '\n'.join(block_lines[content_start:]).strip()
                
                if content:
                    section_concepts = ConceptExtractor.extract_concepts(content, limit=3)
                    
                    pair = {
                        "section_id": idx,
                        "page": page_num,
                        "heading": heading,
                        "instruction": f"Explain this concept from {metadata.get('title', 'the book')}: {heading[:100]}...",
                        "input": "",
                        "output": content,
                        "concepts": section_concepts,
                        "source": metadata.get('title', 'Unknown'),
                        "metadata": {
                            "importance": ConceptExtractor.calculate_importance(content),
                            "word_count": len(content.split())
                        }
                    }
                    lines.append(json.dumps(pair))
        
        return '\n'.join(lines)


@app.route('/extract', methods=['POST'])
def extract_file():
    """Handle file extraction with multiple output formats - optimized for multi-file aggregation"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    file_ext = file.filename.lower().split('.')[-1]
    
    # Save file temporarily
    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, file.filename)
    file.save(temp_path)
    
    try:
        if file_ext == 'pdf':
            extractor = PDFExtractor()
            result = extractor.extract_pdf(temp_path)
        else:
            return jsonify({'error': 'Currently only PDF supported (EPUB/MOBI in progress)'}), 400
        
        if 'error' in result:
            return jsonify(result), 400
        
        # Generate multiple formats
        base_result = result.copy()
        text = result['text']
        metadata = result['metadata']
        concepts = result['concepts']
        
        # Generate all formats
        enhanced_txt = OutputFormatter.generate_enhanced_txt(text, metadata, concepts)
        structured_json = OutputFormatter.generate_structured_json(text, metadata, concepts)
        jsonl = OutputFormatter.generate_jsonl(text, metadata, concepts)
        
        return jsonify({
            'success': True,
            'filename': file.filename,
            'base_info': base_result,
            'formats': {
                'enhanced_txt': enhanced_txt,
                'structured_json': structured_json,
                'jsonl': jsonl
            },
            'stats': {
                'total_sections': len(structured_json['sections']),
                'concepts_found': len(concepts),
                'words': sum(s['metadata']['word_count'] for s in structured_json['sections']),
                'pages': metadata.get('pages', 0)
            }
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        # Cleanup
        try:
            Path(temp_path).unlink(missing_ok=True)
        except:
            pass


@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(debug=True, port=5000)
