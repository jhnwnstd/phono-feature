"""
Main GUI window for the phonology segment and feature engine.

Provides a tabbed interface with:
- Inventory Loader: Load JSON files and view metadata
- Inventory Browser: Table view of all segments and features
- Segment Inspector: Detailed view of individual segments
- Natural Class Finder: Two-way segment/feature interaction
- Feature Geometry: Visualization of feature dependencies (future)
"""

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from engine.feature_engine import FeatureEngine


class InventoryLoaderPanel(QWidget):
    """Panel for loading inventories and displaying metadata."""

    inventory_loaded = pyqtSignal()

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # File selection
        file_group = QGroupBox("Load Inventory")
        file_layout = QHBoxLayout()
        self.file_label = QLabel("No inventory loaded")
        self.load_btn = QPushButton("Browse...")
        self.load_btn.clicked.connect(self.load_inventory)
        file_layout.addWidget(self.file_label)
        file_layout.addWidget(self.load_btn)
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # Quick load buttons
        quick_group = QGroupBox("Quick Load")
        quick_layout = QVBoxLayout()

        # First row
        row1 = QHBoxLayout()
        self.hayes_english_btn = QPushButton("Hayes English (39 seg)")
        self.hayes_english_btn.clicked.connect(
            lambda: self.quick_load("hayes_english.json")
        )
        self.hayes_universal_btn = QPushButton("Hayes Universal (140 seg)")
        self.hayes_universal_btn.clicked.connect(
            lambda: self.quick_load("hayes_universal.json")
        )
        row1.addWidget(self.hayes_english_btn)
        row1.addWidget(self.hayes_universal_btn)

        # Second row
        row2 = QHBoxLayout()
        self.featureize_btn = QPushButton("Featureize (32 seg)")
        self.featureize_btn.clicked.connect(
            lambda: self.quick_load("featureize.json")
        )
        self.blevins_btn = QPushButton("Blevins (141 seg)")
        self.blevins_btn.clicked.connect(
            lambda: self.quick_load("blevins_features.json")
        )
        row2.addWidget(self.featureize_btn)
        row2.addWidget(self.blevins_btn)

        quick_layout.addLayout(row1)
        quick_layout.addLayout(row2)
        quick_group.setLayout(quick_layout)
        layout.addWidget(quick_group)

        # Metadata display
        metadata_group = QGroupBox("Inventory Metadata")
        metadata_layout = QVBoxLayout()
        self.metadata_display = QTextEdit()
        self.metadata_display.setReadOnly(True)
        self.metadata_display.setMaximumHeight(200)
        metadata_layout.addWidget(self.metadata_display)
        metadata_group.setLayout(metadata_layout)
        layout.addWidget(metadata_group)

        # Statistics display
        stats_group = QGroupBox("Inventory Statistics")
        stats_layout = QGridLayout()
        self.stats_labels = {}
        stats_fields = [
            "Segment Count",
            "Feature Count",
            "Contrastive Features",
            "Avg Distance",
        ]
        for i, field in enumerate(stats_fields):
            label = QLabel(f"{field}:")
            value = QLabel("—")
            value.setStyleSheet("font-weight: bold;")
            stats_layout.addWidget(label, i, 0)
            stats_layout.addWidget(value, i, 1)
            self.stats_labels[field] = value
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        layout.addStretch()
        self.setLayout(layout)

    def load_inventory(self):
        """Open file dialog and load inventory."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Inventory", "", "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            try:
                self.engine.load_inventory(file_path)
                self.file_label.setText(os.path.basename(file_path))
                self.update_displays()
                self.inventory_loaded.emit()
                QMessageBox.information(
                    self, "Success", "Inventory loaded successfully!"
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "Error", f"Failed to load inventory:\n{str(e)}"
                )

    def quick_load(self, filename):
        """Quick load from config directory."""
        config_dir = os.path.join(os.path.dirname(__file__), "..", "config")
        file_path = os.path.join(config_dir, filename)
        if os.path.exists(file_path):
            try:
                self.engine.load_inventory(file_path)
                self.file_label.setText(filename)
                self.update_displays()
                self.inventory_loaded.emit()
            except Exception as e:
                QMessageBox.critical(
                    self, "Error", f"Failed to load inventory:\n{str(e)}"
                )
        else:
            QMessageBox.warning(
                self, "Not Found", f"File not found: {filename}"
            )

    def update_displays(self):
        """Update metadata and statistics displays."""
        # Metadata
        metadata_text = ""
        for key, value in self.engine.metadata.items():
            metadata_text += f"<b>{key.title()}:</b> {value}<br>"
        self.metadata_display.setHtml(metadata_text)

        # Statistics
        stats = self.engine.get_inventory_stats()
        self.stats_labels["Segment Count"].setText(str(stats["segment_count"]))
        self.stats_labels["Feature Count"].setText(str(stats["feature_count"]))
        self.stats_labels["Contrastive Features"].setText(
            str(stats["contrastive_features"])
        )
        self.stats_labels["Avg Distance"].setText(
            f"{stats['avg_feature_distance']:.2f}"
        )


class InventoryBrowserPanel(QWidget):
    """Panel for browsing the full inventory in table form."""

    segment_selected = pyqtSignal(str)

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Controls
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Sort by:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Segment (alphabetical)")
        self.sort_combo.currentTextChanged.connect(self.update_table)
        controls.addWidget(self.sort_combo)
        controls.addStretch()
        self.highlight_checkbox = QCheckBox("Highlight contrastive features")
        self.highlight_checkbox.setChecked(True)
        self.highlight_checkbox.stateChanged.connect(self.update_table)
        controls.addWidget(self.highlight_checkbox)
        layout.addLayout(controls)

        # Table
        self.table = QTableWidget()
        self.table.cellClicked.connect(self.on_cell_clicked)
        layout.addWidget(self.table)

        self.setLayout(layout)

    def update_table(self):
        """Rebuild the table with current inventory."""
        if not self.engine.segments:
            return

        segments = sorted(self.engine.segments.keys())
        features = self.engine.features
        contrastive = set(self.engine.get_contrastive_features())

        self.table.setRowCount(len(features))
        self.table.setColumnCount(len(segments))
        self.table.setHorizontalHeaderLabels(segments)
        self.table.setVerticalHeaderLabels(features)

        # Color scheme
        color_plus = QColor(100, 200, 100)  # Green
        color_minus = QColor(200, 100, 100)  # Red
        color_zero = QColor(220, 220, 220)  # Gray
        color_contrastive_bg = QColor(255, 255, 200)  # Light yellow

        highlight = self.highlight_checkbox.isChecked()

        for i, feature in enumerate(features):
            is_contrastive = feature in contrastive
            for j, segment in enumerate(segments):
                value = self.engine.segments[segment].get(feature, "0")
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # Set colors
                if value == "+":
                    item.setBackground(color_plus)
                elif value == "-":
                    item.setBackground(color_minus)
                elif value == "0":
                    item.setBackground(color_zero)

                # Highlight contrastive features
                if highlight and is_contrastive:
                    # Add a subtle yellow tint
                    current_color = item.background().color()
                    blended = QColor(
                        (current_color.red() + color_contrastive_bg.red())
                        // 2,
                        (current_color.green() + color_contrastive_bg.green())
                        // 2,
                        (current_color.blue() + color_contrastive_bg.blue())
                        // 2,
                    )
                    item.setBackground(blended)

                self.table.setItem(i, j, item)

        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()

    def on_cell_clicked(self, row, col):
        """Handle cell click - select segment."""
        segment = self.table.horizontalHeaderItem(col).text()
        self.segment_selected.emit(segment)


class SegmentInspectorPanel(QWidget):
    """Panel for inspecting individual segments in detail."""

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.current_segment = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Segment selector
        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("Segment:"))
        self.segment_combo = QComboBox()
        self.segment_combo.currentTextChanged.connect(self.display_segment)
        selector_layout.addWidget(self.segment_combo)
        selector_layout.addStretch()
        layout.addLayout(selector_layout)

        # Segment display
        self.segment_label = QLabel()
        self.segment_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(48)
        self.segment_label.setFont(font)
        layout.addWidget(self.segment_label)

        # Feature specification
        features_group = QGroupBox("Feature Specification")
        self.features_table = QTableWidget()
        self.features_table.setColumnCount(2)
        self.features_table.setHorizontalHeaderLabels(["Feature", "Value"])
        self.features_table.horizontalHeader().setStretchLastSection(True)
        features_layout = QVBoxLayout()
        features_layout.addWidget(self.features_table)
        features_group.setLayout(features_layout)
        layout.addWidget(features_group)

        # Nearest neighbors
        neighbors_group = QGroupBox("Nearest Phonological Neighbors")
        self.neighbors_list = QListWidget()
        neighbors_layout = QVBoxLayout()
        neighbors_layout.addWidget(self.neighbors_list)
        neighbors_group.setLayout(neighbors_layout)
        layout.addWidget(neighbors_group)

        self.setLayout(layout)

    def update_segments(self):
        """Update the segment selector with current inventory."""
        self.segment_combo.clear()
        if self.engine.segments:
            segments = sorted(self.engine.segments.keys())
            self.segment_combo.addItems(segments)

    def select_segment(self, segment):
        """Programmatically select a segment."""
        index = self.segment_combo.findText(segment)
        if index >= 0:
            self.segment_combo.setCurrentIndex(index)

    def display_segment(self, segment):
        """Display detailed information about a segment."""
        if not segment or segment not in self.engine.segments:
            return

        self.current_segment = segment
        self.segment_label.setText(segment)

        # Feature specification
        features = self.engine.get_segment_features(segment)
        self.features_table.setRowCount(len(features))

        color_plus = QColor(100, 200, 100)
        color_minus = QColor(200, 100, 100)
        color_zero = QColor(220, 220, 220)

        for i, (feature, value) in enumerate(sorted(features.items())):
            feature_item = QTableWidgetItem(feature)
            value_item = QTableWidgetItem(value)
            value_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            if value == "+":
                value_item.setBackground(color_plus)
            elif value == "-":
                value_item.setBackground(color_minus)
            elif value == "0":
                value_item.setBackground(color_zero)

            self.features_table.setItem(i, 0, feature_item)
            self.features_table.setItem(i, 1, value_item)

        self.features_table.resizeColumnsToContents()

        # Nearest neighbors
        self.neighbors_list.clear()
        neighbors = self.engine.find_nearest_segments(segment, n=5)
        for neighbor, distance in neighbors:
            self.neighbors_list.addItem(f"{neighbor}  (distance: {distance})")


class NaturalClassFinderPanel(QWidget):
    """Panel for finding natural classes - two-way interaction."""

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Segments to Features
        seg2feat_group = QGroupBox(
            "Segments → Features: Find characterizing features"
        )
        seg2feat_layout = QVBoxLayout()

        seg2feat_input_layout = QHBoxLayout()
        seg2feat_input_layout.addWidget(QLabel("Segments (space-separated):"))
        self.seg_input = QLineEdit()
        self.seg_input.setPlaceholderText("e.g., p t k")
        seg2feat_input_layout.addWidget(self.seg_input)
        self.seg_find_btn = QPushButton("Find Features")
        self.seg_find_btn.clicked.connect(self.find_features_from_segments)
        seg2feat_input_layout.addWidget(self.seg_find_btn)
        seg2feat_layout.addLayout(seg2feat_input_layout)

        self.seg2feat_result = QTextEdit()
        self.seg2feat_result.setReadOnly(True)
        self.seg2feat_result.setMaximumHeight(150)
        seg2feat_layout.addWidget(self.seg2feat_result)

        seg2feat_group.setLayout(seg2feat_layout)
        layout.addWidget(seg2feat_group)

        # Features to Segments
        feat2seg_group = QGroupBox(
            "Features → Segments: Find matching segments"
        )
        feat2seg_layout = QVBoxLayout()

        feat2seg_input_layout = QHBoxLayout()
        feat2seg_input_layout.addWidget(QLabel("Feature specification:"))
        self.feat_input = QLineEdit()
        self.feat_input.setPlaceholderText("e.g., voice:+,nasal:-")
        feat2seg_input_layout.addWidget(self.feat_input)
        self.feat_find_btn = QPushButton("Find Segments")
        self.feat_find_btn.clicked.connect(self.find_segments_from_features)
        feat2seg_input_layout.addWidget(self.feat_find_btn)
        feat2seg_layout.addLayout(feat2seg_input_layout)

        help_label = QLabel(
            "Format: feature:value,feature:value (e.g., voice:+,continuant:-)"
        )
        help_label.setStyleSheet("color: gray; font-size: 10px;")
        feat2seg_layout.addWidget(help_label)

        self.feat2seg_result = QTextEdit()
        self.feat2seg_result.setReadOnly(True)
        self.feat2seg_result.setMaximumHeight(150)
        feat2seg_layout.addWidget(self.feat2seg_result)

        feat2seg_group.setLayout(feat2seg_layout)
        layout.addWidget(feat2seg_group)

        # Natural classes display
        classes_group = QGroupBox("Natural Class Analysis")
        self.classes_display = QTextEdit()
        self.classes_display.setReadOnly(True)
        classes_layout = QVBoxLayout()
        classes_layout.addWidget(self.classes_display)
        classes_group.setLayout(classes_layout)
        layout.addWidget(classes_group)

        self.setLayout(layout)

    def find_features_from_segments(self):
        """Find features that characterize the given segments."""
        segment_text = self.seg_input.text().strip()
        if not segment_text:
            self.seg2feat_result.setText("Please enter segments.")
            return

        segments = segment_text.split()

        # Validate segments
        invalid = [s for s in segments if s not in self.engine.segments]
        if invalid:
            self.seg2feat_result.setText(
                f"Invalid segments: {', '.join(invalid)}"
            )
            return

        try:
            bundle, is_minimal = self.engine.compute_natural_class(segments)

            result = f"<b>Input segments:</b> {', '.join(segments)}<br>"
            result += f"<b>Class size:</b> {len(segments)}<br><br>"

            result += "<b>Characterizing features:</b><br>"
            if bundle:
                for feature, value in sorted(bundle.items()):
                    result += f"&nbsp;&nbsp;{feature}: {value}<br>"
            else:
                result += "&nbsp;&nbsp;(no distinctive features required)<br>"

            result += f"<br><b>Minimal bundle:</b> {'Yes' if is_minimal else 'No'}<br>"

            # Check if this picks out exactly the target segments
            found_segments = self.engine.find_segments(bundle)
            if set(found_segments) == set(segments):
                result += "<br><span style='color: green;'>✓ Bundle picks out exactly the target segments</span>"
            else:
                result += f"<br><span style='color: orange;'>⚠ Bundle also picks out: {', '.join(set(found_segments) - set(segments))}</span>"

            self.seg2feat_result.setHtml(result)
            self.classes_display.setHtml(
                f"<b>Natural class analysis:</b><br>{result}"
            )

        except Exception as e:
            self.seg2feat_result.setText(f"Error: {str(e)}")

    def find_segments_from_features(self):
        """Find segments matching the given feature specification."""
        feat_text = self.feat_input.text().strip()
        if not feat_text:
            self.feat2seg_result.setText("Please enter feature specification.")
            return

        # Parse feature specification
        try:
            bundle = {}
            pairs = feat_text.split(",")
            for pair in pairs:
                if ":" not in pair:
                    raise ValueError(f"Invalid format: {pair}")
                feature, value = pair.split(":", 1)
                feature = feature.strip()
                value = value.strip()
                if feature not in self.engine.features:
                    raise ValueError(f"Unknown feature: {feature}")
                if value not in ["+", "-", "0"]:
                    raise ValueError(
                        f"Invalid value: {value} (must be +, -, or 0)"
                    )
                bundle[feature] = value

            segments = self.engine.find_segments(bundle)

            result = "<b>Feature specification:</b><br>"
            for feature, value in sorted(bundle.items()):
                result += f"&nbsp;&nbsp;{feature}: {value}<br>"

            result += f"<br><b>Matching segments ({len(segments)}):</b><br>"
            if segments:
                result += "&nbsp;&nbsp;" + ", ".join(segments)
            else:
                result += "&nbsp;&nbsp;(none)"

            self.feat2seg_result.setHtml(result)
            self.classes_display.setHtml(
                f"<b>Natural class analysis:</b><br>{result}"
            )

        except Exception as e:
            self.feat2seg_result.setText(f"Error: {str(e)}")


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.engine = FeatureEngine()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Phonology Segment & Feature Engine")
        self.setGeometry(100, 100, 1200, 800)

        # Create tab widget
        self.tabs = QTabWidget()

        # Create panels
        self.loader_panel = InventoryLoaderPanel(self.engine)
        self.browser_panel = InventoryBrowserPanel(self.engine)
        self.inspector_panel = SegmentInspectorPanel(self.engine)
        self.natural_class_panel = NaturalClassFinderPanel(self.engine)

        # Connect signals
        self.loader_panel.inventory_loaded.connect(self.on_inventory_loaded)
        self.browser_panel.segment_selected.connect(self.on_segment_selected)

        # Add tabs
        self.tabs.addTab(self.loader_panel, "Inventory Loader")
        self.tabs.addTab(self.browser_panel, "Inventory Browser")
        self.tabs.addTab(self.inspector_panel, "Segment Inspector")
        self.tabs.addTab(self.natural_class_panel, "Natural Class Finder")

        self.setCentralWidget(self.tabs)

        # Status bar
        self.statusBar().showMessage("Ready. Load an inventory to begin.")

    def on_inventory_loaded(self):
        """Handle inventory loaded event."""
        self.browser_panel.update_table()
        self.inspector_panel.update_segments()

        # Auto-populate sort combo with features
        current_features = ["Segment (alphabetical)"] + self.engine.features
        self.browser_panel.sort_combo.clear()
        self.browser_panel.sort_combo.addItems(current_features)

        self.statusBar().showMessage(
            f"Loaded: {self.engine.metadata.get('name', 'Inventory')} "
            f"({len(self.engine.segments)} segments, {len(self.engine.features)} features)"
        )

    def on_segment_selected(self, segment):
        """Handle segment selection from browser."""
        self.tabs.setCurrentWidget(self.inspector_panel)
        self.inspector_panel.select_segment(segment)
