from pextant.MeshModel import Mesh
from pextant.solvers.astarSEXTANT import ExpandViz
from pextant.lib.geoshapely import GeoPoint, LAT_LONG
import numpy as np

origin = GeoPoint(LAT_LONG, 43.461621,-113.572019)
data = np.zeros([30,30])
mm = Mesh(origin, data)
ev = ExpandViz(mm)
ev.add((3,4),5)
ev.add((2,2),5)
ev.add((0,0),5)
ev.draw()