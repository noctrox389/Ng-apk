from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.clock import Clock
from kivy.lang import Builder
import os
from android.storage import primary_external_storage_path
from android.permissions import request_permissions, Permission
from PIL import Image, ImageChops
import xml.etree.ElementTree as ET
import re
import shutil
import math
from concurrent.futures import ThreadPoolExecutor
from kivy.utils import platform

# Request permissions
if platform == 'android':
    request_permissions([
        Permission.READ_EXTERNAL_STORAGE,
        Permission.WRITE_EXTERNAL_STORAGE
    ])

Builder.load_string('''
<FolderSelector>:
    orientation: 'vertical'
    padding: 10
    spacing: 10
    TextInput:
        id: path_input
        hint_text: 'Enter folder path'
        size_hint_y: None
        height: 40
    BoxLayout:
        size_hint_y: None
        height: 40
        spacing: 10
        Button:
            text: 'Cancel'
            on_press: root.dismiss()
        Button:
            text: 'Select'
            on_press: root.select_path()
''')

class FolderSelector(BoxLayout):
    def __init__(self, callback, **kwargs):
        super().__init__(**kwargs)
        self.callback = callback
    
    def select_path(self):
        path = self.ids.path_input.text
        if os.path.exists(path):
            self.callback(path)
            self.parent.parent.dismiss()
    
    def dismiss(self):
        self.parent.parent.dismiss()

class SpriteProcessor(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.spacing = 10
        self.padding = 20
        
        # Title
        self.add_widget(Label(text='Sprite Processor', font_size=24, size_hint_y=None, height=50))
        
        # Input
        self.input_btn = Button(text='Select INPUT Folder', size_hint_y=None, height=50)
        self.input_btn.bind(on_press=lambda x: self.show_folder_dialog('input'))
        self.add_widget(self.input_btn)
        self.input_label = Label(text='Not selected', size_hint_y=None, height=30)
        self.add_widget(self.input_label)
        
        # Output
        self.output_btn = Button(text='Select OUTPUT Folder', size_hint_y=None, height=50)
        self.output_btn.bind(on_press=lambda x: self.show_folder_dialog('output'))
        self.add_widget(self.output_btn)
        self.output_label = Label(text='Not selected', size_hint_y=None, height=30)
        self.add_widget(self.output_label)
        
        # Options
        options = BoxLayout(spacing=10, size_hint_y=None, height=60)
        self.extract_btn = Button(text='Extract Frames')
        self.extract_btn.bind(on_press=self.extract_frames)
        options.add_widget(self.extract_btn)
        
        self.resize_btn = Button(text='Resize')
        self.resize_btn.bind(on_press=self.resize_frames)
        options.add_widget(self.resize_btn)
        
        self.pack_btn = Button(text='Create Sprites')
        self.pack_btn.bind(on_press=self.create_sprites)
        options.add_widget(self.pack_btn)
        self.add_widget(options)
        
        # Progress
        self.progress = ProgressBar(max=100, size_hint_y=None, height=20)
        self.add_widget(self.progress)
        self.status = Label(text='Ready', size_hint_y=None, height=30)
        self.add_widget(self.status)
        
        # Footer
        self.add_widget(Label(text='Created by Noctrox Gato', size_hint_y=None, height=30))
        
        # Variables
        self.input_path = ''
        self.output_path = ''
        self.base_path = primary_external_storage_path() if platform == 'android' else os.path.expanduser('~')
    
    def show_folder_dialog(self, mode):
        content = FolderSelector(callback=lambda path: self.set_folder(path, mode))
        popup = Popup(title=f'Select {mode.upper()} Folder', 
                     content=content,
                     size_hint=(0.9, 0.5))
        content.ids.path_input.text = self.base_path
        popup.open()
    
    def set_folder(self, path, mode):
        if mode == 'input':
            self.input_path = path
            self.input_label.text = f'INPUT: {os.path.basename(path)}'
        else:
            self.output_path = path
            self.output_label.text = f'OUTPUT: {os.path.basename(path)}'
    
    def extract_frames(self, instance):
        if not self._check_paths():
            return
        
        self.status.text = "Extracting frames..."
        Clock.schedule_once(lambda dt: self._extract_frames_async())
    
    def _extract_frames_async(self):
        try:
            tasks = []
            skip_dirs = {'frames_output', 'Quegod', 'frames'}
            
            for root, dirs, files in os.walk(self.input_path):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for file in files:
                    if file.endswith(".png"):
                        png_path = os.path.join(root, file)
                        xml_path = os.path.splitext(png_path)[0] + ".xml"
                        if os.path.exists(xml_path):
                            try:
                                tree = ET.parse(xml_path)
                                root_xml = tree.getroot()
                                frame_count = len(root_xml.findall(".//SubTexture"))
                                relative_path = os.path.relpath(os.path.dirname(png_path), self.input_path)
                                tasks.append((png_path, xml_path, relative_path, frame_count))
                            except ET.ParseError:
                                self._update_status(f"Error in {xml_path}, skipping")
            
            if not tasks:
                self._update_status("No valid PNG/XML files found")
                return
            
            total_frames = sum(task[3] for task in tasks)
            self.progress.max = total_frames
            self.progress.value = 0
            
            with ThreadPoolExecutor() as executor:
                futures = []
                for png_path, xml_path, relative_path, frame_count in tasks:
                    futures.append(executor.submit(
                        self._process_sprite_sheet, png_path, xml_path, relative_path
                    ))
                
                for future in futures:
                    future.result()
            
            self._update_status(f"Extracted {total_frames} frames")
        
        except Exception as e:
            self._update_status(f"Error: {str(e)}")
    
    def _process_sprite_sheet(self, png_path, xml_path, relative_path):
        try:
            image = Image.open(png_path).convert("RGBA")
            tree = ET.parse(xml_path)
            root = tree.getroot()
            png_name = os.path.splitext(os.path.basename(png_path))[0]
            
            frame_output_dir = os.path.join(self.output_path, relative_path, png_name)
            os.makedirs(frame_output_dir, exist_ok=True)
            
            canvas_size_file = os.path.join(frame_output_dir, f"{image.width}x{image.height}.txt")
            with open(canvas_size_file, 'w') as f:
                f.write(f"Original dimensions: {image.width}x{image.height}")
            
            subtextures = root.findall(".//SubTexture")
            
            for subtexture in subtextures:
                name = re.sub(r'[<>:"/\\|?*]', '_', subtexture.attrib['name'])
                x = int(float(subtexture.attrib.get('x', 0)))
                y = int(float(subtexture.attrib.get('y', 0)))
                width = int(float(subtexture.attrib.get('width', 0)))
                height = int(float(subtexture.attrib.get('height', 0)))
                frameX = int(float(subtexture.attrib.get('frameX', 0)))
                frameY = int(float(subtexture.attrib.get('frameY', 0)))
                frameWidth = int(float(subtexture.attrib.get('frameWidth', width)))
                frameHeight = int(float(subtexture.attrib.get('frameHeight', height)))
                rotated = subtexture.attrib.get('rotated', 'false').lower() == 'true'
                
                sprite_crop = image.crop((x, y, x + width, y + height))
                if rotated:
                    sprite_crop = sprite_crop.transpose(Image.ROTATE_90)
                    width, height = height, width
                
                frame_image = Image.new("RGBA", (frameWidth, frameHeight), (0, 0, 0, 0))
                paste_x = -frameX if frameX < 0 else 0
                paste_y = -frameY if frameY < 0 else 0
                frame_image.paste(sprite_crop, (paste_x, paste_y))
                
                frame_path = os.path.join(frame_output_dir, f"{name}.png")
                frame_image.save(frame_path, "PNG")
                
                self._update_progress(1)
        
        except Exception as e:
            self._update_status(f"Error processing {png_path}: {str(e)}")
    
    def resize_frames(self, instance):
        if not self._check_paths():
            return
        
        self.status.text = "Resizing frames..."
        Clock.schedule_once(lambda dt: self._resize_frames_async())
    
    def _resize_frames_async(self):
        try:
            total_files = 0
            for root, dirs, files in os.walk(self.input_path):
                total_files += len([f for f in files if f.endswith('.png')])
            
            if total_files == 0:
                self._update_status("No PNG files found")
                return
            
            self.progress.max = total_files
            self.progress.value = 0
            
            for root, dirs, files in os.walk(self.input_path):
                rel_path = os.path.relpath(root, self.input_path)
                export_path = os.path.join(self.output_path, rel_path)
                os.makedirs(export_path, exist_ok=True)
                
                dim = self._get_dimensions_from_txt(root)
                factor = self._calculate_factor(dim)
                
                images = [f for f in files if f.endswith('.png')]
                if not images:
                    continue
                
                for img_file in images:
                    input_file = os.path.join(root, img_file)
                    output_file = os.path.join(export_path, img_file)
                    try:
                        self._resize_image(input_file, output_file, factor)
                        self._update_progress(1)
                    except Exception as e:
                        self._update_status(f"Error in {img_file}: {str(e)}")
                
                if factor != 1.0:
                    txt_path = os.path.join(export_path, f"{os.path.basename(root)}.txt")
                    with open(txt_path, "w") as f:
                        f.write(f"{round(1 / factor, 2)}")
            
            self._update_status(f"Resized {total_files} images")
        
        except Exception as e:
            self._update_status(f"Error: {str(e)}")
    
    def _get_dimensions_from_txt(self, folder_path):
        txt_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.txt')]
        for txt_file in txt_files:
            with open(os.path.join(folder_path, txt_file), 'r') as f:
                content = f.read().strip()
                matches = re.findall(r'(\d+)x(\d+)', content)
                if matches:
                    return tuple(map(int, matches[0]))
        return None
    
    def _calculate_factor(self, dim):
        if not dim:
            return 1.0
        width, height = dim
        average = (width + height) / 2
        if average >= 8192:
            return 0.25
        elif 4096 <= average < 8192:
            return 0.4
        elif 2048 <= average < 4096:
            return 0.5
        return 1.0
    
    def _resize_image(self, image_path, output_path, factor):
        img = Image.open(image_path)
        new_size = (int(img.width * factor), int(img.height * factor))
        resized = img.resize(new_size, Image.Resampling.LANCZOS)
        resized.save(output_path)
        os.remove(image_path)
    
    def create_sprites(self, instance):
        if not self._check_paths():
            return
        
        self.status.text = "Creating sprite sheets..."
        Clock.schedule_once(lambda dt: self._create_sprites_async())
    
    def _create_sprites_async(self):
        try:
            image_folders = self._find_leaf_folders(self.input_path)
            total_folders = len(image_folders)
            
            if total_folders == 0:
                self._update_status("No image folders found")
                return
            
            self.progress.max = total_folders
            self.progress.value = 0
            
            for folder in image_folders:
                relative_path = os.path.relpath(folder, self.input_path)
                final_output_dir = os.path.join(self.output_path, os.path.dirname(relative_path))
                os.makedirs(final_output_dir, exist_ok=True)
                
                original_folder_name = os.path.basename(folder)
                image_files = sorted([file for file in os.listdir(folder) if file.endswith(('png', 'jpg', 'jpeg'))])
                images = [Image.open(os.path.join(folder, file)) for file in image_files]
                
                unique_images = []
                unique_image_files = []
                duplicate_image_files = []
                seen_images = set()
                original_sizes = {}
                bboxes = {}
                sprite_dict = {}
                image_hash_map = {}
                
                for img, file_name in zip(images, image_files):
                    img_hash = hash(img.tobytes())
                    if img_hash not in image_hash_map:
                        image_hash_map[img_hash] = (img, file_name)
                        unique_images.append(img)
                        unique_image_files.append(file_name)
                        original_sizes[file_name] = img.size
                    else:
                        duplicate_image_files.append((img_hash, file_name))
                
                trimmed_images = []
                for img in unique_images:
                    trimmed_img, bbox = self._trim(img)
                    trimmed_images.append(trimmed_img)
                    bboxes[unique_image_files[unique_images.index(img)]] = bbox
                
                grouped_images = self._group_images(trimmed_images)
                total_area = sum((w + 10) * (h + 10) for img_list in grouped_images.values() for img in img_list for w, h in [img.size])
                initial_sheet_size = math.ceil(math.sqrt(total_area))
                
                max_width = max(img.width for img in trimmed_images)
                max_height = max(img.height for img in trimmed_images)
                sheet_size = max(initial_sheet_size, max_width, max_height)
                
                while True:
                    try:
                        spritesheet = Image.new("RGBA", (sheet_size, sheet_size), (0, 0, 0, 0))
                        x_offset, y_offset = 0, 0
                        max_height_in_row = 0
                        root = ET.Element("TextureAtlas", imagePath=original_folder_name)
                        
                        for file_name, img in zip(unique_image_files, trimmed_images):
                            if x_offset + img.width + 10 > sheet_size:
                                x_offset = 0
                                y_offset += max_height_in_row + 10
                                max_height_in_row = 0
                            
                            if y_offset + img.height + 10 > sheet_size:
                                raise ValueError("Increase sheet size")
                            
                            spritesheet.paste(img, (x_offset, y_offset))
                            original_size = original_sizes[file_name]
                            bbox = bboxes[file_name]
                            
                            sprite = ET.SubElement(root, "SubTexture")
                            sprite.set("name", os.path.splitext(file_name)[0])
                            sprite.set("x", str(x_offset))
                            sprite.set("y", str(y_offset))
                            sprite.set("width", str(img.width))
                            sprite.set("height", str(img.height))
                            sprite.set("frameWidth", str(original_size[0]))
                            sprite.set("frameHeight", str(original_size[1]))
                            sprite.set("frameX", str(-bbox[0]))
                            sprite.set("frameY", str(-bbox[1]))
                            
                            sprite_dict[file_name] = {
                                "x": str(x_offset),
                                "y": str(y_offset),
                                "width": str(img.width),
                                "height": str(img.height),
                                "frameWidth": str(original_size[0]),
                                "frameHeight": str(original_size[1]),
                                "frameX": str(-bbox[0]),
                                "frameY": str(-bbox[1])
                            }
                            
                            x_offset += img.width + 10
                            max_height_in_row = max(max_height_in_row, img.height)
                        
                        for img_hash, file_name in duplicate_image_files:
                            original_file_name = image_hash_map[img_hash][1]
                            sprite = ET.SubElement(root, "SubTexture")
                            sprite.set("name", os.path.splitext(file_name)[0])
                            for key, value in sprite_dict[original_file_name].items():
                                sprite.set(key, value)
                        
                        sorted_subelements = sorted(root.findall('SubTexture'), key=lambda x: x.get('name', ''))
                        for subelement in sorted_subelements:
                            root.remove(subelement)
                            root.append(subelement)
                        
                        spritesheet_path = os.path.join(final_output_dir, f"{original_folder_name}.png")
                        spritesheet.save(spritesheet_path)
                        
                        xml_str = ET.tostring(root, encoding='utf-8')
                        xml_str = minidom.parseString(xml_str).toprettyxml(indent="    ")
                        xml_comment = "<?xml version='1.0' encoding='utf-8'?>\n<!-- CREATED BY NOCTROX GATO -->\n"
                        xml_str = xml_comment + xml_str.split("?>", 1)[1].strip()
                        
                        xml_file_path = os.path.join(final_output_dir, f"{original_folder_name}.xml")
                        with open(xml_file_path, "w") as xml_file:
                            xml_file.write(xml_str)
                        
                        txt_path = os.path.join(folder, f"{original_folder_name}.txt")
                        if os.path.exists(txt_path):
                            shutil.copy2(txt_path, os.path.join(final_output_dir, f"{original_folder_name}.txt"))
                        
                        break
                    except ValueError:
                        sheet_size = int(sheet_size * 1.1)
                        self._update_status(f"Increasing sheet size to {sheet_size}x{sheet_size}")
                
                self._update_progress(1)
            
            self._update_status(f"Created {total_folders} sprite sheets")
        
        except Exception as e:
            self._update_status(f"Error: {str(e)}")
    
    def _find_leaf_folders(self, folder):
        leaf_folders = []
        for root, dirs, files in os.walk(folder):
            image_files = [f for f in files if f.lower().endswith(('png', 'jpg', 'jpeg'))]
            if image_files:
                leaf_folders.append(root)
        return leaf_folders
    
    def _trim(self, image):
        bg = Image.new(image.mode, image.size, (0, 0, 0, 0))
        diff = ImageChops.difference(image, bg)
        bbox = diff.getbbox()
        if bbox:
            return image.crop(bbox), bbox
        return image, (0, 0, image.width, image.height)
    
    def _group_images(self, images):
        grouped_images = {}
        for img in images:
            size = img.size
            if size not in grouped_images:
                grouped_images[size] = []
            grouped_images[size].append(img)
        return grouped_images
    
    def _check_paths(self):
        if not self.input_path:
            self._update_status("Error: Select input folder")
            return False
        if not self.output_path:
            self._update_status("Error: Select output folder")
            return False
        return True
    
    def _update_progress(self, value=1):
        self.progress.value += value
        Clock.schedule_once(lambda dt: None)
    
    def _update_status(self, message):
        self.status.text = message
        Clock.schedule_once(lambda dt: None)

class SpriteProcessorApp(App):
    def build(self):
        self.title = "Sprite Processor"
        return SpriteProcessor()

if __name__ == "__main__":
    SpriteProcessorApp().run()