import json

import pandas as pd
from copy import deepcopy
from pextant.lib.geoshapely import *
import re

def loadPointsOld(filename):
    parsed_json = json.loads(jsonInput)
    waypoints = []

    for element in parsed_json:  # identify all of the waypoints
        if element["type"] == "Station":
            lon, lat = element["geometry"]["coordinates"]
            time_cost = element["userDuration"]
            waypoints.append(GeoPolygon(LAT_LONG, lon, lat))

    return waypoints, parsed_json


class JSONloader:
    def __init__(self, filepath):
        self.filepath = filepath
        self.extension = '_plan.json'
        self.filename = re.search('^(.+\/[^/]+)(\.\w+)$', filepath).group(1)
        with open(filepath) as data_file:
            self.jsondata = json.load(data_file)

    def get_waypoints(self):
        ways_and_segments = self.jsondata['sequence']
        s = pd.DataFrame(ways_and_segments)
        waypoints = s[s['type'] == 'Station']['geometry']
        w = waypoints.values.tolist()
        latlongFull = pd.DataFrame(w)
        latlongInter = latlongFull['coordinates'].values.tolist()
        waypointslatlong = pd.DataFrame(latlongInter, columns=['longitude', 'latitude'])
        return GeoPolygon(LAT_LONG, waypointslatlong['latitude'].values, waypointslatlong['longitude'].values)

    def get_segments(self):
        ways_and_segments = self.jsondata['sequence']
        s = pd.DataFrame(ways_and_segments)
        waypoints = s[s['type'] == 'Segment']['geometry']
        w = waypoints.values.tolist()
        latlongFull = pd.DataFrame(w)
        latlongInter = latlongFull['coordinates'].values.tolist()
        waypointslatlong = np.array(latlongInter[0])
        return GeoPolygon(LAT_LONG, waypointslatlong[:, 1], waypointslatlong[:, 0])

    def add_search_sol(self, segments, write_to_file=False):
        search_json_data = deepcopy(self.jsondata)
        ways_and_segments = search_json_data['sequence']
        segment_iter = iter(segments)
        for i, element in enumerate(ways_and_segments):
            if element["type"] == "Segment":
                segment = segment_iter.next()
                ways_and_segments[i]["derivedInfo"].update(segment["derivedInfo"]) #merges our new info
                ways_and_segments[i]["geometry"] = segment["geometry"]
        raw_json = json.dumps(search_json_data)
        formatted_json = json.dumps(search_json_data, indent=4, sort_keys=True)
        if write_to_file:
            new_filename = self.filename + self.extension
            with open(new_filename, 'w') as outfile:
                outfile.write(formatted_json)
        return raw_json


if __name__ == '__main__':
    jloader = JSONloader('../../data/waypoints/HI_13Nov16_MD7_A.json')