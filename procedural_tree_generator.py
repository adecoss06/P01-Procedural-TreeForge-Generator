import os
import math
import random

import maya.cmds as cmds
import maya.mel as mel
import maya.OpenMayaUI as omui

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import wrapInstance


# Name Conventions
WINDOW_OBJECT = "ProceduralTreeGeneratorWindow"
WINDOW_TITLE = "Procedural Tree Generator"
GENERATED_GROUP = "PTG_Tree_GRP"


def maya_main_window():
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QWidget)


def _maya_user_dir():
    return cmds.internalVar(userAppDir=True)


def create_custom_icon():
    icon_dir = os.path.join(_maya_user_dir(), "prefs", "icons")
    if not os.path.isdir(icon_dir):
        os.makedirs(icon_dir)
    icon_path = os.path.join(icon_dir, "procedural_tree_generator.png")

    pix = QtGui.QPixmap(64, 64)
    pix.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pix)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    # trunk
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QColor(112, 72, 42))
    painter.drawRoundedRect(QtCore.QRectF(28, 35, 8, 23), 2, 2)
    # foliage layers
    painter.setBrush(QtGui.QColor(52, 145, 91))
    painter.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(32, 3), QtCore.QPointF(11, 31),
        QtCore.QPointF(53, 31)]))
    painter.setBrush(QtGui.QColor(66, 170, 105))
    painter.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(32, 14), QtCore.QPointF(5, 43),
        QtCore.QPointF(59, 43)]))
    painter.setBrush(QtGui.QColor(42, 125, 78))
    painter.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(32, 26), QtCore.QPointF(10, 52),
        QtCore.QPointF(54, 52)]))
    painter.end()
    pix.save(icon_path, "PNG")
    return icon_path


def install_shelf_button():
    icon_path = create_custom_icon()
    shelf = mel.eval("$tmp = $gShelfTopLevel")
    current = cmds.tabLayout(shelf, query=True, selectTab=True)
    children = cmds.shelfLayout(current, query=True, childArray=True) or []
    for child in children:
        if cmds.shelfButton(child, exists=True):
            child_label = cmds.shelfButton(child, query=True, label=True)
            if child_label == "Tree Generator":
                cmds.deleteUI(child)
    module_dir = os.path.dirname(os.path.abspath(__file__))

    command = (
        "import sys; "
        "sys.path.insert(0, %r); "
        "import procedural_tree_generator as ptg; "
        "ptg.show_tool()"
    ) % module_dir

    cmds.shelfButton(parent=current, label="Tree Generator",
                     annotation="Open Procedural Tree Generator",
                     image=icon_path, imageOverlayLabel="TREE",
                     sourceType="python", command=command)


def _make_material(name, color, roughness=0.72):
    shader = cmds.shadingNode("lambert", asShader=True, name=name)
    cmds.setAttr(
        shader + ".color",
        color[0], color[1], color[2],
        type="double3"
    )
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name=name + "SG")
    cmds.connectAttr(
        shader + ".outColor",
        sg + ".surfaceShader",
        force=True
    )
    return sg


def _point_between(a, b, t):
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def _vector(a, b):
    return (b[0] - a[0], b[1] - a[1], b[2] - a[2])


def _length(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _make_branch(start, end, radius, material, name, sides=7):
    vec = _vector(start, end)
    length = _length(vec)
    if length < 0.001:
        return None
    node = cmds.polyCylinder(name=name, radius=radius, height=length,
                             subdivisionsAxis=sides, subdivisionsHeight=1,
                             subdivisionsCaps=1, constructionHistory=False)[0]
    angle = cmds.angleBetween(euler=True, v1=(0, 1, 0), v2=vec)
    cmds.xform(node, worldSpace=True,
               translation=_point_between(start, end, 0.5),
               rotation=angle)
    cmds.sets(node, edit=True, forceElement=material)
    return node


def generate_tree(settings):
    """Builds a deterministic tree from the supplied UI settings."""
    rng = random.Random(settings["seed"])
    if cmds.objExists(GENERATED_GROUP):
        cmds.delete(GENERATED_GROUP)
    root = cmds.group(empty=True, name=GENERATED_GROUP)

    trunk_mat = _make_material("PTG_Bark_MAT", (0.24, 0.12, 0.055))
    leaf_colors = {
        "Summer": (0.12, 0.42, 0.16),
        "Spring": (0.35, 0.62, 0.18),
        "Autumn": (0.68, 0.25, 0.06),
        "Fantasy": (0.20, 0.38, 0.72),
    }
    leaf_mat = _make_material("PTG_Leaves_MAT",
                              leaf_colors[settings["season"]])

    height = settings["height"]
    spread = settings["spread"]
    levels = settings["levels"]
    density = settings["density"]
    style = settings["shape"]
    branch_count = settings["branches"]
    trunk_radius = max(0.12, height * 0.045)

    # Slightly irregular segmented trunk
    trunk_points = [(0.0, 0.0, 0.0)]
    for i in range(1, 5):
        trunk_points.append((rng.uniform(-0.12, 0.12) * i,
                             height * i / 4.0,
                             rng.uniform(-0.12, 0.12) * i))
    for i in range(4):
        r = trunk_radius * (1.0 - 0.78 * (i / 4.0))
        node = _make_branch(trunk_points[i], trunk_points[i + 1],
                            r, trunk_mat, "PTG_Trunk_%02d" % i, 10)
        cmds.parent(node, root)

    leaf_centers = []

    def crown_factor(y_ratio):
        if style == "Medium":
            return 0.58 + 0.12 * y_ratio
        if style == "Weeping":
            return 0.35 + 0.95 * (1.0 - y_ratio)
        if style == "Low":
            return math.sqrt(max(0.08, 1.0 - (2.0 * y_ratio - 1.0) ** 2))
        return 1.0 - 0.55 * y_ratio  # Tall

    def grow(start, direction, length, radius, depth, parent_name):
        if depth <= 0 or length < height * 0.055:
            leaf_centers.append(start)
            return
        end = (start[0] + direction[0] * length,
               start[1] + direction[1] * length,
               start[2] + direction[2] * length)
        node = _make_branch(start, end, radius, trunk_mat,
                            "PTG_Branch_%s_%d" % (parent_name, depth), 6)
        if node:
            cmds.parent(node, root)
        leaf_centers.append(end)

        count = max(2, branch_count - (levels - depth))
        for j in range(count):
            t = 0.42 + (0.48 * (j / max(1, count - 1)))
            origin = _point_between(start, end, t)
            angle = (2.0 * math.pi * j / count) + rng.uniform(-0.35, 0.35)
            y_ratio = max(0.0, min(1.0, origin[1] / height))
            radial = spread * crown_factor(y_ratio) * (0.62 + 0.38 * t)
            if style == "Weeping":
                dy = -0.28 + rng.uniform(-0.18, 0.10)
            else:
                dy = 0.42 + rng.uniform(-0.12, 0.28)
            child_dir = (math.cos(angle) * radial,
                         dy,
                         math.sin(angle) * radial)
            mag = _length(child_dir)
            child_dir = tuple(v / mag for v in child_dir)
            grow(origin, child_dir, length * rng.uniform(0.56, 0.72),
                 radius * 0.62, depth - 1,
                 parent_name + str(j))

    # Main limbs emerge around the upper trunk.
    for i in range(branch_count):
        y = height * rng.uniform(0.42, 0.88)
        origin = (rng.uniform(-0.07, 0.07),
                  y,
                  rng.uniform(-0.07, 0.07))
        angle = 2.0 * math.pi * i / branch_count + rng.uniform(-0.25, 0.25)
        y_ratio = y / height
        radial = spread * crown_factor(y_ratio)
        direction = (math.cos(angle) * radial,
                     rng.uniform(0.28, 0.62),
                     math.sin(angle) * radial)
        mag = _length(direction)
        direction = tuple(v / mag for v in direction)
        grow(origin, direction, height * rng.uniform(0.27, 0.38),
             trunk_radius * 0.48, levels - 1, "M%d" % i)

    # Low-poly leaf clusters 
    leaf_total = max(20, int(density * 5))
    if not leaf_centers:
        leaf_centers = [(0, height, 0)]
    for i in range(leaf_total):
        center = leaf_centers[i % len(leaf_centers)]
        offset = (rng.uniform(-spread * 0.25, spread * 0.25),
                  rng.uniform(-spread * 0.18, spread * 0.18),
                  rng.uniform(-spread * 0.25, spread * 0.25))
        pos = (center[0] + offset[0], center[1] + offset[1],
               center[2] + offset[2])
        size = rng.uniform(0.16, 0.34) * (height / 8.0)
        leaf = cmds.polySphere(name="PTG_LeafCluster_%03d" % i,
                               radius=size, subdivisionsAxis=5,
                               subdivisionsHeight=4,
                               constructionHistory=False)[0]
        cmds.xform(leaf, worldSpace=True, translation=pos,
                   rotation=(rng.uniform(0, 360), rng.uniform(0, 360),
                             rng.uniform(0, 360)),
                   scale=(rng.uniform(0.75, 1.2), rng.uniform(0.65, 1.1),
                          rng.uniform(0.75, 1.2)))
        cmds.sets(leaf, edit=True, forceElement=leaf_mat)
        cmds.parent(leaf, root)

    cmds.select(root, replace=True)
    cmds.xform(root, centerPivots=True)
    cmds.setAttr(root + ".visibility", 1)
    return root


class ProceduralTreeGenerator(QtWidgets.QDialog):
    def __init__(self, parent=maya_main_window()):
        super(ProceduralTreeGenerator, self).__init__(parent)
        self.setObjectName(WINDOW_OBJECT)
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumWidth(360)
        self.setWindowFlags(
            self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        main = QtWidgets.QVBoxLayout(self)
        main.setContentsMargins(16, 16, 16, 16)
        main.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        icon_label = QtWidgets.QLabel()
        icon = QtGui.QPixmap(create_custom_icon()).scaled(
            52, 52, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        icon_label.setPixmap(icon)
        header.addWidget(icon_label)
        title_col = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("TREE FORGE")
        title.setObjectName("title")
        subtitle = QtWidgets.QLabel("Procedural environment asset builder")
        subtitle.setObjectName("subtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col)
        header.addStretch()
        main.addLayout(header)

        form = QtWidgets.QFormLayout()
        form.setVerticalSpacing(9)
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.height = self._spin(2.0, 30.0, 8.0, 0.5)
        self.spread = self._spin(0.4, 3.0, 1.35, 0.05)
        self.levels = self._spin(1, 5, 3, 1, integer=True)
        self.branches = self._spin(3, 9, 5, 1, integer=True)
        self.density = self._spin(10, 100, 55, 1, integer=True)
        self.seed = self._spin(0, 99999, 12, 1, integer=True)

        self.shape = QtWidgets.QComboBox()
        self.shape.addItems(["Tall", "Low", "Medium", "Weeping"])
        self.season = QtWidgets.QComboBox()
        self.season.addItems(["Summer", "Spring", "Autumn", "Fantasy"])

        form.addRow("Tree height", self.height)
        form.addRow("Crown spread", self.spread)
        form.addRow("Branching levels", self.levels)
        form.addRow("Primary branches", self.branches)
        form.addRow("Foliage density", self.density)
        form.addRow("Branch Direction", self.shape)
        form.addRow("Foliage palette", self.season)
        form.addRow("Random seed", self.seed)
        main.addLayout(form)

        self.randomize_btn = QtWidgets.QPushButton("↻  Randomize Seed")
        self.randomize_btn.clicked.connect(self.randomize_seed)
        main.addWidget(self.randomize_btn)

        self.generate_btn = QtWidgets.QPushButton("GENERATE TREE")
        self.generate_btn.setObjectName("generate")
        self.generate_btn.setMinimumHeight(42)
        self.generate_btn.clicked.connect(self.on_generate)
        main.addWidget(self.generate_btn)

        footer = QtWidgets.QLabel(
            "Tip: Change the seed to explore new branching layouts!")
        footer.setObjectName("footer")
        footer.setWordWrap(True)
        main.addWidget(footer)

    def _spin(self, minimum, maximum, value, step, integer=False):
        widget = (
            QtWidgets.QSpinBox()
            if integer else QtWidgets.QDoubleSpinBox()
        )
        if integer:
            widget.setRange(int(minimum), int(maximum))
        else:
            widget.setRange(minimum, maximum)
        widget.setValue(int(value) if integer else value)
        widget.setSingleStep(int(step) if integer else step)
        if not integer:
            widget.setDecimals(2)
        return widget

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog { background: #252a2d; color: #e8eceb; }
            QLabel { color: #dce4df; font-size: 12px; }
            QLabel#title {
                color: #8bd3a4; font-size: 21px; font-weight: 800;
                letter-spacing: 2px;
            }
            QLabel#subtitle { color: #9daaa3; font-size: 10px; }
            QLabel#footer {
                color: #9daaa3; font-size: 10px; padding-top: 5px;
            }
            QDoubleSpinBox, QSpinBox, QComboBox {
                background: #343c3e; color: #f1f5f2; border: 1px solid #4a5854;
                border-radius: 5px; padding: 5px; min-height: 22px;
            }
            QComboBox::drop-down { border: 0px; width: 22px; }
            QPushButton {
                background: #3a4842; color: #eaf5ed; border: 1px solid #52675a;
                border-radius: 6px; padding: 8px; font-weight: 600;
            }
            QPushButton:hover { background: #4b6254; }
            QPushButton#generate {
                background: #278653; border: 0px; color: white;
                font-size: 13px; font-weight: 800;
            }
            QPushButton#generate:hover { background: #32a566; }
        """)

    def randomize_seed(self):
        self.seed.setValue(random.randint(0, 99999))

    def on_generate(self):
        settings = {
            "height": self.height.value(),
            "spread": self.spread.value(),
            "levels": self.levels.value(),
            "branches": self.branches.value(),
            "density": self.density.value(),
            "shape": self.shape.currentText(),
            "season": self.season.currentText(),
            "seed": self.seed.value(),
        }
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("GENERATING...")
        QtWidgets.QApplication.processEvents()
        try:
            generate_tree(settings)
            cmds.inViewMessage(amg="<hl>Tree generated</hl> — PTG_Tree_GRP",
                               pos="topCenter", fade=True)
        except Exception as exc:
            cmds.warning("Procedural Tree Generator: %s" % exc)
            QtWidgets.QMessageBox.critical(self, "Generation failed", str(exc))
        finally:
            self.generate_btn.setEnabled(True)
            self.generate_btn.setText("GENERATE TREE")


_TOOL_INSTANCE = None


def show_tool():
    global _TOOL_INSTANCE
    try:
        if _TOOL_INSTANCE is not None:
            _TOOL_INSTANCE.close()
            _TOOL_INSTANCE.deleteLater()
    except Exception:
        pass
    _TOOL_INSTANCE = ProceduralTreeGenerator()
    _TOOL_INSTANCE.show()
    _TOOL_INSTANCE.raise_()
    _TOOL_INSTANCE.activateWindow()
    return _TOOL_INSTANCE


# RUN
def run():
    install_shelf_button()
    show_tool()


if __name__ == "__main__":
    run()