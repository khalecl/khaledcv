from flask import Flask, request, jsonify
from flask_cors import CORS
import fitz  # PyMuPDF
import zipfile
import io
import re
from pathlib import Path
import json

app = Flask(__name__)
CORS(app)

class PDFExtractor:
    def __init__(self):
        self.markers = 0
        self.images = []
        
    def extract_pdf(self, file_path):
        """Extract text with structure from PDF"""
        try:
            doc = fitz.open(file_path)
            full_text = ""
            self.markers = 0
            self.images = []
            
            # Get metadata
            metadata = doc.metadata
            
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
            
            doc.close()
            return {
                'text': full_text.strip(),
                'metadata': {
                    'title': metadata.get('title', 'Unknown'),
                    'author': metadata.get('author', 'Unknown'),
                    'pages': len(doc),
                    'creation_date': metadata.get('creationDate', 'N/A')
                },
                'markers': self.markers,
                'images_found': len(self.images)
            }
        except Exception as e:
            return {'error': str(e)}
    
    def _extract_headings(self, blocks):
        """Extract potential headings from text blocks"""
        headings = []
        for block in blocks:
            if block[1]:  # Text block
                font_size = block[4]
                if font_size and font_size > 14:
                    text = block[4].strip()
                    if len(text) < 100:
                        headings.append(text)
        return headings[:1]  # Return first heading


class EPUBExtractor:
    def extract_epub(self, file_path):
        """Extract text from EPUB"""
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                # Find content.opf for metadata
                opf_path = self._find_file(zip_ref, '.opf')
                metadata = self._extract_metadata(zip_ref, opf_path) if opf_path else {}
                
                # Extract HTML files (chapters)
                html_files = [f for f in zip_ref.namelist() 
                             if f.endswith('.html') or f.endswith('.xhtml')]
                html_files.sort()
                
                full_text = ""
                markers = 0
                
                for idx, html_file in enumerate(html_files, 1):
                    try:
                        content = zip_ref.read(html_file).decode('utf-8', errors='ignore')
                        text = self._extract_text_from_html(content)
                        
                        if text.strip():
                            full_text += f"[SECTION]: Chapter {idx}\n"
                            full_text += text + "\n\n"
                            markers += 2
                    except:
                        continue
                
                return {
                    'text': full_text.strip(),
                    'metadata': metadata,
                    'markers': markers,
                    'chapters': len(html_files)
                }
        except Exception as e:
            return {'error': str(e)}
    
    def _find_file(self, zip_ref, extension):
        """Find first file with given extension"""
        for name in zip_ref.namelist():
            if name.endswith(extension):
                return name
        return None
    
    def _extract_text_from_html(self, html):
        """Extract clean text from HTML"""
        # Remove script and style
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '\n', html)
        
        # Clean up whitespace
        text = re.sub(r'\n\s*\n', '\n', text)
        text = re.sub(r' +', ' ', text)
        
        return text.strip()
    
    def _extract_metadata(self, zip_ref, opf_path):
        """Extract metadata from OPF file"""
        try:
            opf_content = zip_ref.read(opf_path).decode('utf-8', errors='ignore')
            title = re.search(r'<dc:title[^>]*>([^<]+)</dc:title>', opf_content)
            author = re.search(r'<dc:creator[^>]*>([^<]+)</dc:creator>', opf_content)
            
            return {
                'title': title.group(1) if title else 'Unknown',
                'author': author.group(1) if author else 'Unknown'
            }
        except:
            return {}


class MOBIExtractor:
    def extract_mobi(self, file_path):
        """Basic MOBI extraction (reads as binary)"""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            
            # Extract readable text
            text_matches = re.findall(b'[a-zA-Z\s.,!?;:\'"()\-]{50,}', content)
            full_text = ""
            markers = 0
            
            for idx, match in enumerate(text_matches[:100], 1):  # Limit sections
                try:
                    text = match.decode('utf-8', errors='ignore').strip()
                    if len(text) > 100:
                        full_text += f"[SECTION]: Section {idx}\n{text}\n\n"
                        markers += 2
                except:
                    continue
            
            return {
                'text': full_text.strip(),
                'metadata': {'title': Path(file_path).stem},
                'markers': markers
            }
        except Exception as e:
            return {'error': str(e)}


@app.route('/extract', methods=['POST'])
def extract_file():
    """Handle file extraction"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    file_ext = file.filename.lower().split('.')[-1]
    
    # Save file temporarily
    temp_path = f'/tmp/{file.filename}'
    file.save(temp_path)
    
    try:
        if file_ext == 'pdf':
            extractor = PDFExtractor()
            result = extractor.extract_pdf(temp_path)
        elif file_ext == 'epub':
            extractor = EPUBExtractor()
            result = extractor.extract_epub(temp_path)
        elif file_ext == 'mobi':
            extractor = MOBIExtractor()
            result = extractor.extract_mobi(temp_path)
        else:
            return jsonify({'error': 'Unsupported file format'}), 400
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        # Cleanup
        Path(temp_path).unlink(missing_ok=True)


@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(debug=True, port=5000)
