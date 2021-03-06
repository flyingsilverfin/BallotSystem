#!/usr/bin/python

"""
This script periodically polls a google doc and updates a set of .json files in the ballot_name/data/ folder
These files get pulled by the client which correspondingly update the svg on the frontend
"""

import time
import os
import shutil
import sys
import json


import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import httplib2 # for hacky token refresh 

#these are prefixes in the room_id_translation.csv file
# these are toplevel json keys
SITES = [
	"bbc_a", "bbc_b", "bbc_c",
	"cs_1", "cs_2",
	"boho_a", "boho_b", "boho_c", 
	"new_build_a",
		"new_build_e", "new_build_f", "new_build_g", "new_build_h", "new_build_i",  "new_build_j",
		"new_build_k", "new_build_l", "new_build_m", "new_build_n", "new_build_o", "new_build_p", 
	"wyng_a" , "wyng_b", "wyng_c", "wyng_d",
	"coote"
] 

def to_date(date_string):
	return datetime.strptime(date_string[:19], '%Y-%m-%dT%H:%M:%S')

def copyIndex(dest, key):
	fIn = open("template/index.html")
	fOut = open(os.path.join(dest, 'index.html'), "w")
	for line in fIn:
		if "REPLACE_THIS_WITH_KEY" in line:
			line = line.replace("REPLACE_THIS_WITH_KEY", key)
		fOut.write(line)
	fIn.close()
	fOut.close()

def run():
	
	config = json.load(open('backend/config/config.json'))
	ballot_doc_columns = config['ballot_document_columns']
	name_index = ballot_doc_columns['roomName']

	only_init = config['only_init']
	sheet_name = config['sheet_name']

	year = config['year']
	name = str(year)

	try:
		os.mkdir('./ballot')
	except Exception:
		pass
	instance_dir = os.path.join('./ballot', name)



	if not only_init:
		# use creds to create a client to interact with the Google Drive API
		scope = ['https://spreadsheets.google.com/feeds']
		creds = ServiceAccountCredentials.from_json_keyfile_name('backend/config/google_api_secret.json', scope)
		
		def authorize():
			return gspread.authorize(creds)

		client = authorize()

		def get_sheet():
			# get the most recently edited spreadsheet as the current one
			documents = client.openall()
			documents.sort(key=lambda s: to_date(s.updated), reverse=True)
			doc = documents[0]
		
			for s in doc.worksheets():
				if sheet_name == s.title:
					return s, doc
	
		sheet, doc = get_sheet()
		spreadsheet_key = doc.id
	else:
		spreadsheet_key = -1

	
	# delete all the existing files and just copy over from scratch
	# in init-only we wrote a -1 to the ID...
	
	try:
		shutil.rmtree(instance_dir)
	except Exception:
		pass
	try:
		os.mkdir(instance_dir)	#throws an exception caught by outer level if already exists
		shutil.copy("template/scripts_new.js", instance_dir)
		copyIndex(instance_dir, spreadsheet_key )	#copy and edit
		shutil.copy("template/svgStyling.css", instance_dir)
		shutil.copy("template/style.css", instance_dir)
		shutil.copy("template/.htaccess", instance_dir)
		shutil.copytree("template/res", os.path.join(instance_dir, "res"))
	except Exception:
		if verbose:
			print("File or Directory exists/error, continuing")

	if only_init:
		print("Finished copying files in only_init mode, exiting")
		return


	print("Starting ballot: ", instance_dir)


	ballotDocument = BallotSpreadsheet(name_index, ballot_doc_columns)
	roomTranslator = RoomTranslator('backend/config/room_id_mapping.csv')
	jsonSiteWriter = JSONFileWriter(instance_dir)
	sites_data = SitesData(SITES, ballotDocument, roomTranslator)


	last_update = to_date(doc.updated)
	init = True
	last_auth = datetime.now()

	while True:
		time.sleep(5)
		sheet, doc = get_sheet()

		if  (datetime.now() - last_auth).total_seconds() > 60 * 15:
			print("Reauthorizing")
			creds.refresh(httplib2.Http())
			client = authorize()
			last_auth = datetime.now()
#		print(doc.updated)
#		print(last_update)
#		print(to_date(doc.updated) <= last_update)
#		if not init:  # not supported anymore...  and to_date(doc.updated) <= last_update:
#			continue
#		last_update = to_date(doc.updated)

		print("\n*Polling online spreadsheet", doc)
		if verbose:
			print("Pulling new changes")
		

		# update class-representation of the google doc (legacy adapted)
		for row in sheet.get_all_values():
			room_name = row[name_index]
			if not roomTranslator.is_valid_room(room_name):
				continue
			if ballotDocument.hasKey(room_name):
				if ballotDocument.hasBeenUpdated(row):
					ballotDocument.update(row)
			else:
				ballotDocument.addRow(row)

                updated = sites_data.update()
                if updated or init:
                    # only 1 JSON file now
                    jsonSiteWriter.writeJSONFile("data", sites_data.get_json_string())

		init = False



# *** everything below here is from prior version and could be redone ***


#this is fed rows of the spreadsheet
#like ["BBC A01", 'BS', '\xc2\xa3106.96', 'Cooper', 'Domy', 'crsid', 'Easter', ''],
#the row layout is as set in BALLOT_DOCUMENT_COLS
class BallotSpreadsheet:
	def __init__(self, name_index, columns):
		self.data = {}
		self.name_index = name_index
		self.columns = columns
		
	def hasKey(self, key):
		for keys in self.data:
			if keys.startswith(key):
				return True
		return False
	
	def getKey(self, key):
		for k in self.data:
			if k.startswith(key):
				return self.data[k]
				
	def toAttrDictionary(self, row):
		attrs = {}
		for attr in self.columns:
			index = self.columns[attr]
			if index == -1: 	# signal values to ignore
				attrs[attr] = ''  #but this attr may be hard coded in somewhere...
			else:
				attrs[attr] = row[self.columns[attr]]
		return attrs
	
	def addRow(self, row):
		if verbose:
			print("ADDING ROW TO BALLOT SPREADSHEET: " + str(row))
		self.data[row[self.name_index]] = self.toAttrDictionary(row)

	def hasBeenUpdated(self, row):
		return self.data[row[self.name_index]] != self.toAttrDictionary(row)
	
	def update(self, row):
		self.data[row[self.name_index]] = self.toAttrDictionary(row)
	
	def isTaken(self, key):
		d = self.getKey(key)
		if d['surname'].strip() == "" and d['name'].strip() == "":
			return False
		return True

	def getOccupier(self, key): 
		d = self.getKey(key)
		return d['name'] + " " + d['surname']
	
	def getWeeklyRent(self, key):
		d = self.getKey(key)
		if len(d) == 0:	#
			return -1
		return d['weeklyRent']
		
	def getFullCostString(self, key):
		contract = self.getContractType(key)
		if 'term' in contract.lower():
			return "30 weeks: &pound;" + str(float(self.getWeeklyRent(key).strip())*30)
		else: #calculate both easter and yearly cost
			
			#note on calculation: during the holidays, so for about 25 days each holiday, you pay 80% of the cost
			s = "30 week: ~&pound;" + str(float(self.getWeeklyRent(key).strip())*30)
			s += "\nEaster: ~&pound;" + str(round(float(self.getWeeklyRent(key).strip())*(30 + 0.8 * 3.5),2))
			s += "\nYear: ~&pound;" + str(round(float(self.getWeeklyRent(key).strip()) * ( 30 + 0.8*7),2))
			return s
	
	def getRoomType(self, key): #could later add a dict to convert the spreadsheet codes to the text
		d = self.getKey(key)
		return d['roomType']
	
	def getCrsid(self, key):
		d = self.getKey(key)
		return d['crsid']
	
	#this one's tricky because some rooms are term only
	#could do something that marks rooms if they're not taken yet
	#but have term contract written in (== SET)
	def getContractType(self, key):
		d = self.getKey(key)
		return d['license']


	def getFloor(self, name):
		d = self.getKey(name)
		return d['floor']

	def getNotes(self, name):
		d = self.getKey(name)
		return d['notes']
	
	def printContents(self):
		for key in self.data:
			print(key, self.data[key])
		
		
#this takes the csv file as the translation between
#the ballot document room names and the SVG file room id's
#this class has no concept of which rooms are actually in the ballot
#it simply translates between values in the translation CSV file
class RoomTranslator:
	def __init__(self, roomIdTranslationFile):
		self.roomIdTranslationFile = roomIdTranslationFile
		self.data = {}
		tmp = open(self.roomIdTranslationFile).readlines()

		for line in tmp:
			d = line.strip().split(",")
			#do it in reverse for now... not sure which way is better
			self.data[d[0]] = d[1]
	

	def is_valid_room(self, name):
		return name in self.data.values()

	def convertSVGId(self, id):
		if id in self.data:
			return self.data[id]
		else:
			raise Exception("ID " + id + " does not exist in ballot sheet")
		
	def printContents(self):
		print("---Printing contents of Room Translator ---")
		for key in self.data:
			print(key + ": " + self.data[key])
		
	#wrote this one as a generator for fun!
	def getRoomsFromSite(self, site):
		for room in self.data:
			if room.startswith(site):
				yield room
	


class SitesData:
    def __init__(self, sitenames, ballot_doc, room_translator):
        self.data = {}
        for site in sitenames:
            self.data[site] = SiteDataHolder(site, ballot_doc, room_translator)

    # returns if any have updated
    def update(self):
        updated = False 
        for site in self.data.values():
	    b = site.update()
            updated = updated or b
        return updated

    def get_json_string(self):
        d = {}
        for site_name in self.data:
	    site = self.data[site_name]
            d[site_name] = site.get_JSON()
        return json.dumps(d)
			
"""
This will duplicate all the data. Might rewrite later but good enough for now
"""
class SiteDataHolder:
	def __init__(self, site, ballotDocument, roomTranslator):
		self.rooms = {}
		self.site = site
		self.ballotDocument = ballotDocument
		self.roomTranslator = roomTranslator
		#build initial data
		print("Building data for: " + site)

		for room in self.roomTranslator.getRoomsFromSite(self.site):
			if verbose:
				print("\tROOM: " + room)

			ballotRoomName = self.roomTranslator.convertSVGId(room)
			info = self.buildStatusJSON(ballotRoomName)
			self.rooms[room] = info
			
	#def buildStatusList(self, ballotRoomName):
	def buildStatusJSON(self, ballotRoomName):
		if self.ballotDocument.hasKey(ballotRoomName) and ballotRoomName != "":
			info = {}
			info['status'] = "occupied" if self.ballotDocument.isTaken(ballotRoomName) else "available"
			#info = ["occupied" if self.ballotDocument.isTaken(ballotRoomName) else "available"]
			info['roomName'] = ballotRoomName
			#info.append(ballotRoomName)
			info['occupier'] = self.ballotDocument.getOccupier(ballotRoomName)
#			info.append(self.ballotDocument.getOccupier(ballotRoomName))
			info['occupierCrsid'] = self.ballotDocument.getCrsid(ballotRoomName)
#			info.append(self.ballotDocument.getCrsid(ballotRoomName))
			info['roomPrice'] = self.ballotDocument.getWeeklyRent(ballotRoomName)
#			info.append(self.ballotDocument.getWeeklyRent(ballotRoomName))
			info['contractType'] = self.ballotDocument.getContractType(ballotRoomName)
#			info.append(self.ballotDocument.getContractT	pe(ballotRoomName))
			info['roomType'] = self.ballotDocument.getRoomType(ballotRoomName)
#			info.append(self.ballotDocument.getRoomType(ballotRoomName))
			info['fullCost'] = self.ballotDocument.getFullCostString(ballotRoomName)

			info['floor'] = self.ballotDocument.getFloor(ballotRoomName)
			info['notes'] = self.ballotDocument.getNotes(ballotRoomName)
			return info
		else:
			info = { 'status' : "unavailable"}
			return info
		
	#note: this doesn't handle new rooms to the translation file
	def update(self):
		updated = False
		for room in self.rooms:
			ballotName = self.roomTranslator.convertSVGId(room)
			info = self.buildStatusJSON(ballotName)
			if verbose:
				print(room)
				print(ballotName)
				print(info)
				print("prior:")
				print(self.rooms[room])
			if self.rooms[room] != info:
				updated = True
				self.rooms[room] = info
		return updated
			

        def get_JSON(self):
            return self.rooms

	def getJSONString(self):
		if verbose:
			print(self.rooms)
		return json.dumps(self.rooms)


class JSONFileWriter:
	def __init__(self, path):
		self.path = path
	def writeJSONFile(self, site, jsonString):
		print("\t\tMaking data file: " + site + ".json")

		try:
			os.mkdir(os.path.join(self.path, "data"))
		except OSError: #directory already exists
			pass
		fOut = open(os.path.join(self.path, "data", site + ".json"), 'w')
		fOut.write(jsonString)
		fOut.close()


if __name__ == "__main__":
	verbose = False 
	run()
