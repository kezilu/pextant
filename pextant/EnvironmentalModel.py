import re

import numpy.ma as ma
from osgeo import gdal, osr

from pextant.lib.geoshapely import *
from pextant.lib.geoutils import filled_grid_circle
from pextant.mesh.abstractmesh import GeoMesh, EnvironmentalModel, \
    SearchKernel, coordinate_transform, Dataset, NpDataset
from pextant.mesh.abstractcomponents import MeshCollection
from pextant.mesh.concretecomponents import MeshElement
from pathlib2 import Path
from itertools import count

class GDALDataset(Dataset):
    '''
    This is a wrapper that gives gdal datasets a shape property, similar to numpy arrays
    '''
    def __init__(self, dataset, row_size, col_size, resolution):
        super(GDALDataset, self).__init__(dataset, row_size, col_size, resolution)
        self.raster = dataset
        self.map_array = None

    # override interpolator since the data set is just a shell
    def _grid_interpolator_initializer(self):
        return lambda : None

    def subsection(self, x_offset, y_offset, x_size, y_size, desired_res=None):
        buf_x = None
        buf_y = None
        if desired_res:
            buf_x = int(x_size * self.resolution / desired_res)
            buf_y = int(y_size * self.resolution / desired_res)
        else:
            desired_res = self.resolution

        band = self.raster.GetRasterBand(1)
        map_array = band.ReadAsArray(x_offset, y_offset, x_size, y_size, buf_x, buf_y).astype(np.float)
        self.map_array = map_array
        dataset_clean = ma.masked_array(map_array, np.isnan(map_array)).filled(-99999)
        dataset_clean = NpDataset(ma.masked_array(dataset_clean, dataset_clean < -2e3), desired_res)
        return dataset_clean

class GridMesh(GeoMesh):
    def __init__(self, *arg, **kwargs):
        super(GridMesh, self).__init__(*arg, **kwargs)
        self.ROW_COL = Cartesian(self.nw_geo_point, self.resolution, reverse=True)
        self.COL_ROW = Cartesian(self.nw_geo_point, self.resolution)

    def subsection(self, geo_envelope=None, desired_res=None):
        """
                :param geo_envelope:
                :type geo_envelope pextant.geoshapely.GeoEnvelope
                :param desired_res:
                :return:
        """
        map_nw_corner, map_se_corner  = self.nw_geo_point, GeoPoint(self.COL_ROW, self.x_size, self.y_size)

        if geo_envelope is not None:
            selection_nw_corner, selection_se_corner = geo_envelope.getBounds()
        else:
            selection_nw_corner, selection_se_corner = map_nw_corner, map_se_corner

        map_box = GeoPolygon([map_nw_corner, map_se_corner]).envelope
        selection_box = GeoEnvelope(selection_nw_corner, selection_se_corner).envelope
        intersection_box = map_box.intersection(selection_box)

        inter_easting, inter_northing = np.array(intersection_box.bounds).reshape((2, 2)).transpose()
        intersection_box_geo = GeoPolygon(self.nw_geo_point.utm_reference, inter_easting, inter_northing)  # could change to UTM_AUTO later
        inter_x, inter_y = intersection_box_geo.to(self.COL_ROW)

        x_offset, max_x = inter_x
        max_y, y_offset = inter_y
        # TODO: need to explain the +1, comes from hack. Also, doesnt work when selecting full screen
        x_size = max_x - x_offset + 1
        y_size = max_y - y_offset + 1
        if geo_envelope is None:
            x_size -= 1
            y_size -= 1

        dataset_clean = self.dataset.subsection(x_offset, y_offset, x_size, y_size, desired_res)

        # TODO: this hack needs explanation
        nw_coord_hack = GeoPoint(self.nw_geo_point.utm_reference, inter_easting.min(), inter_northing.max())\
            .to(self.COL_ROW)
        nw_coord = GeoPoint(self.COL_ROW, nw_coord_hack[0], nw_coord_hack[1])
        meta_mesh = GridMesh(nw_coord, dataset_clean, parent_mesh=self,
                             xoff=x_offset, yoff=y_offset)
        return meta_mesh

    def loadSubSection(self, geo_envelope=None, desired_res=None, **kwargs):
        #kwargs is reserved for max slope argument
        sub_mesh = self.subsection(geo_envelope, desired_res)
        return GridMeshModel.from_parent(sub_mesh, **kwargs)

class GDALMesh(GridMesh):
    """
    This class should be used for loading all GeoTiff terrains, and any subset thereof
    """

    def __init__(self, file_path):
        if isinstance(file_path, Path):
            file_path = str(file_path.absolute())
        self.file_path = file_path
        gdal.UseExceptions()
        dataset = gdal.Open(file_path)
        x_size = dataset.RasterXSize
        y_size = dataset.RasterYSize

        dataset_info = dataset.GetGeoTransform()
        nw_easting = dataset_info[0]
        nw_northing = dataset_info[3]
        resolution = dataset_info[1]
        dataset_wrapped = GDALDataset(dataset, row_size=y_size, col_size=x_size,
                                      resolution=resolution)

        proj = dataset.GetProjection()
        srs = osr.SpatialReference(wkt=proj)
        projcs = srs.GetAttrValue('projcs')  # "NAD83 / UTM zone 5N"...hopefully
        regex_result = re.search('zone(\s|\_)(\d+)(\w)', projcs, flags=re.IGNORECASE)
        if regex_result:
            zone_number = regex_result.group(2)  # zone letter is group(2)
            nw_geo_point = GeoPoint(UTM(zone_number), nw_easting, nw_northing)
        else:
            nw_geo_point = GeoPoint(UTM(0), 0, 0)

        super(GDALMesh, self).__init__(nw_geo_point, dataset_wrapped)

class GridMeshModel(EnvironmentalModel):
    def __init__(self, *arg, **kwargs):
        super(GridMeshModel, self).__init__(*arg, **kwargs)
        self.dataset_unmasked = self.data.filled(0) if isinstance(self.data, np.ma.core.MaskedArray) else self.data
        self.isvaliddata = np.logical_not(self.data.mask)  if isinstance(self.data, np.ma.core.MaskedArray) \
            else np.ones_like(self.data).astype(bool)
        self.searchKernel = SearchKernel(self.kernel_size, self.kernel_type)
        self.ROW_COL = Cartesian(self.nw_geo_point, self.resolution, reverse=True)
        self.COL_ROW = Cartesian(self.nw_geo_point, self.resolution)
        self.cached_neighbours = self._cache_neighbours() if self.cached else []

    def _getMeshElement(self, mesh_coordinates):
        if len(self._inBounds(mesh_coordinates))>0:
            #TODO: need to make this a function:
            mesh_coordinates = mesh_coordinates[0]
            geo_coordinates = mesh_coordinates[::-1]*self.resolution
            return MeshElement(self, mesh_coordinates, geo_coordinates)
        else:
            raise IndexError("The location (%s, %s) is out of bounds" %
                             (mesh_coordinates[0], mesh_coordinates[1]))

    def _getNeighbours(self, mesh_coordinates):
        state = np.array(mesh_coordinates)
        kernel = self.searchKernel
        offset = kernel.getKernel()
        if self.cached:
            selection = self.cached_neighbours[state[0],state[1]]
            passable_neighbours = state + offset[selection]
        else:
            potential_neighbours = state + offset
            passable_neighbours = self._isPassable(potential_neighbours)
        # TODO: need to make this a function:
        coordsxy =  np.fliplr(passable_neighbours)*self.resolution
        return MeshCollection(self, passable_neighbours.transpose(), coordsxy.transpose())

    def setSlopes(self):
        [gy, gx] = np.gradient(self.data, self.resolution, self.resolution)
        self.slopes = np.degrees(
            np.arctan(np.sqrt(np.add(np.square(gx), np.square(gy)))))  # Combining for now for less RAM usage

    def setRadialKeepOutZone(self, center, radius):
        circlex, circley = filled_grid_circle(radius)
        self.obstacles[center+circlex, center+circley] = 1

    def getElevations(self, mesh_coordinates):
        #IMPORTANT assumes the elevation requested is not masked
        row, col = mesh_coordinates
        return self.dataset_unmasked[row,col]

    @coordinate_transform
    def getSlope(self, coordinates):
        row, col = coordinates
        return self.slopes[row,col]

    def _inBounds(self, mesh_coordinates):
        # determines if a coordinate is within the boundaries of the environmental model
        boolean = self._inbounds_bool(mesh_coordinates)
        return mesh_coordinates[boolean]

    def _inbounds_bool(self, mesh_coordinates):
        below_bounds = mesh_coordinates < self.shape
        over_bounds = mesh_coordinates >= np.zeros(2)
        boolean = np.logical_and(below_bounds, over_bounds).all(1)
        return boolean

    def _hasdata(self, mesh_coordinates):
        bounded = self._inBounds(mesh_coordinates)
        row, col = bounded.transpose()
        return bounded[self.isvaliddata[row, col]]

    @coordinate_transform
    def elt_hasdata(self, mesh_coordinate):
        return len(self._hasdata(mesh_coordinate)) > 0

    def maxSlopeObstacle(self, maxSlope):
        self.obstacles = self.slopes > maxSlope
        self.passable = np.logical_not(self.obstacles)

    def _isPassable(self, mesh_coordinates):
        valid_data = self._hasdata(mesh_coordinates)
        row, col = valid_data.transpose()
        return valid_data[self.passable[row, col]]

    def convert_coordinates(self, coordinates):
        if isinstance(coordinates, GeoPoint):
            return np.array([coordinates.to(self.ROW_COL)])
        elif isinstance(coordinates, np.ndarray):
            return coordinates
        else:
            return np.array([coordinates])

    #TODO: move to parent class
    def cache_neighbours(self):
        self.cached_neighbours = self._cache_neighbours()
        return self.cached_neighbours

    def _cache_neighbours(self):
        #print('precomputing neighbours')
        rows, cols = np.mgrid[0:self.y_size, 0:self.x_size]
        gridpoints = np.array([rows.flatten(), cols.flatten()]).transpose()

        kernel = self.searchKernel
        offsets = kernel.getKernel()
        s = np.empty((self.shape[0], self.shape[1], len(offsets)), dtype=bool)
        dr = np.apply_along_axis(np.linalg.norm, 1, offsets) * self.resolution
        z = self.dataset_unmasked
        neighbour_size = len(self.searchKernel.getKernel())
        #slopes_rad = np.empty((self.shape[0], self.shape[1], neighbour_size))
        for idx, offset in enumerate(offsets):
            candidate_neighbour_point = gridpoints + offset
            point_is_neighbour = self._inbounds_bool(candidate_neighbour_point) # if not in bounds, its not a neighbour
            inbound_rows, inbound_cols = candidate_neighbour_point[point_is_neighbour].transpose()
            point_is_neighbour[point_is_neighbour] = self.isvaliddata[inbound_rows, inbound_cols]
            hasdata_rows, hasdata_cols = candidate_neighbour_point[point_is_neighbour].transpose()
            point_is_neighbour[point_is_neighbour] = self.passable[hasdata_rows, hasdata_cols]
            #dri = dr[idx]
            #slopes_rad = np.arctan2(np.roll(np.roll(z, -offset[0], axis=0), -offset[1], axis=1) - z, dri)
            #not_too_steep = np.degrees(slopes_rad) <= self.maxSlope
            #is_passable = np.reshape(point_is_neighbour, self.shape)
            #s[:, :, idx] = np.logical_and(is_passable, not_too_steep)
            s[:,:,idx] = np.reshape(point_is_neighbour, self.shape)
        return s


def loadElevationMap(fullPath, maxSlope=35, nw_corner=None, se_corner=None, desiredRes=None):
    geoenvelope = GeoEnvelope(nw_corner, se_corner)
    #maxSlope=25 #TODO: need to fix this
    dem = GDALMesh(fullPath)
    return dem.loadSubSection(geoenvelope, maxSlope=maxSlope, desired_res=desiredRes)

def load_legacy(filename):
    m = Path(filename)
    name = m.stem
    d = {}
    c = count()
    r = True

    def num(s):
        try:
            return int(s)
        except ValueError:
            return float(s)

    with m.open() as f:
        while r:
            c.next()
            r = re.search("([^\d\W]+)\s+(-*\d+\.*\d*)", f.readline())
            if r:
                d[r.groups()[0]] = num(r.groups()[1])
    l = c.next() - 1
    data = np.loadtxt(str(m.resolve()), skiprows=l)
    dataset = NpDataset(data, resolution=d["cellsize"])
    if "UTMzone" in d:
        gp = GeoPoint(UTM("UTMzone"), d["xllcorner"], d["yllcorner"])
    else:
        gp = GeoPoint(UTM(1), d["xllcorner"], d["yllcorner"])
    return GridMesh(gp, dataset)

if __name__ == '__main__':
    from pextant.lib.utils import gridpoints_list
    ames_em = GDALMesh('../data/maps/Ames/Ames.tif').loadSubSection(maxSlope=25)
    #cProfile.run('ames_em.cache_neighbours()')
    s = ames_em.cache_neighbours()
    positions = gridpoints_list(ames_em)
    kernel = ames_em.searchKernel.getKernel()
    for position in positions:
        n1 = ames_em._getNeighbours(position).mesh_coordinates
        n2 = (position + kernel[s[position[0], position[1]]]).transpose()
        if not np.array_equal(n1, n2):
            print 'Houston we have a problem'
    print "Houston we don't have a problem'"
