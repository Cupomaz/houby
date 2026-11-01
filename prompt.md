i have two maps of the czech republic. 

one is a .png file of a mushroom probability map. 
Coordinate System: WGS84 (EPSG:4326)
xmin (Min Longitude / West): 12.0424913
ymin (Min Latitude / South): 48.403695
xmax (Max Longitude / East): 19.1177213
ymax (Max Latitude / North): 51.0596505

it has the following colors with ids:

0 #d93629
1 #f88d51
2 #ffffbf
3 #86cb66
4 #219b51

0 is lowest probability and 4 is the highest.


the second is a map of forest and their age in the czech republic.
its provided as a WMTS service. the capabilities are at https://geoportal.lesycr.cz/WMTS_LCR/service.svc/get?request=GetCapabilities&service=WMTS

this is the map:
https://geoportal.lesycr.cz/WMTS_LCR/service.svc/get?
  SERVICE=WMTS&
  REQUEST=GetTile&
  VERSION=1.0.0&
  LAYER=POROSTLCR&
  STYLE=default&
  FORMAT=image/png&
  TILEMATRIXSET=JTSK:epsg:5514&
  TILEMATRIX=9&
  TILEROW={row}&
  TILECOL={col}

the colors indicate forest age

0 #ffff29 1-20 years
1 #ff8b62 21-40 years
2 #b4ff00 41-60 years
3 #a4ffff 61-80 years
4 #de8b00 81-100 years
5 #9c9c9c 101-120 years
6 #d57bff 121-140 years
7 #0fff73 141 and more years



i want to make an intersection of each forest age and the highest and second highest mushroom probability and overlay it on a czech map. i want the finished thing to be available in a web browser. i thought about using leafletjs but if you have something better you can use that. i want there to be a menu to select the forest age to display. python will be used for the backend