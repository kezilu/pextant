import MeshModel
from ipywidgets import interact
from bokeh.io import push_notebook, show, output_notebook
from bokeh.plotting import figure
import numpy as np
import matplotlib.pyplot as plt
from pextant.lib.geoshapely import GeoPolygon

class ExpandViz(object):
    def __init__(self, env_model, counter_interval=1000):
        self.env_model = env_model
        self.expandedgrid = np.zeros((env_model.numRows, env_model.numCols))
        self.counter = 0
        self.counter_interval = counter_interval
        self.expanded = []

    #cmap = 'viridis'
    def draw(self):
        expanded = np.array(self.expanded).transpose()
        gp_expanded = GeoPolygon(self.env_model.ROW_COL,*expanded)
        upper_left, lower_right = gp_expanded.geoEnvelope()
        upper_row, left_col = upper_left.to(self.env_model.ROW_COL)
        lower_row, right_col = lower_right.to(self.env_model.ROW_COL)
        plt.matshow(self.expandedgrid[upper_row:lower_row+1,left_col:right_col+1])
        print((upper_row, lower_row), (left_col,right_col))
        #print(waypoints.to(env_model.COL_ROW))
        #plt.scatter(*waypoints.to(env_model.COL_ROW), c='r')
        plt.show()

    def drawsolution(self, rawpoints):
        np_rawpoints = GeoPolygon(self.env_model.ROW_COL, *np.array(rawpoints).transpose())
        plt.matshow(self.env_model.dataset)
        #plt.scatter(*waypoints.to(env_model.COL_ROW), c='r')
        plt.scatter(*np_rawpoints.to(self.env_model.COL_ROW), c='b')
        plt.show()

    def add(self, state, cost):
        self.expanded.append(np.array(state))
        self.expandedgrid[state] = cost
        self.counter += 1

        if self.counter % self.counter_interval == 0:
            print self.counter

        if self.counter % self.counter_interval == 0:
            self.draw()

class MeshViz:
    def __init__(self, notebook=False):
        self.notebook = notebook
        if notebook:
            output_notebook()

    def viz(self, mesh, x=None, y=None, palette="Spectral11", viz=True):
        dh, dw = mesh.shape
        size = max(dh, dw)
        self.mesh = mesh
        self.dh = dh
        self.dw = dw
        self.p = figure(webgl=True, title="MD2", x_axis_label='x', y_axis_label='y', x_range=[0, size], y_range=[0, size])
        self.p.image(image=[mesh[::-1, :]], x=0, y=0, dw=dw, dh=dh, palette=palette)
        if not x is None:
            #self.p.line(x, self.dh - np.array(y), line_color="green", line_width=3)
            self.p.circle(x, self.dh - np.array(y), fill_color="green", line_color="black", size=10)
        if self.notebook and viz:
            self.t = show(self.p, notebook_handle = self.notebook)
        else:
            #self.t = show(self.p)
            pass

    def show(self):
        self.t = show(self.p, notebook_handle = self.notebook)

    def vizpoints(self, x, y):
        print(x)
        self.p.circle(y, self.dh - np.array(x), fill_color="yellow", size=10)
        push_notebook(handle=self.t)

class MeshVizM:
    def __init__(self):
        pass

    def viz(self, mesh, x=None, y=None):
        plt.matshow(mesh)
        plt.show()


if __name__ == '__main__':
    MeshViz().viz(np.zeros([4,4]))