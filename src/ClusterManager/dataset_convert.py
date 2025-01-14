import json
import os
import time
import argparse
import uuid
import subprocess
import sys
import datetime
reload(sys)
sys.setdefaultencoding('utf8')
import yaml
from jinja2 import Environment, FileSystemLoader, Template
import base64

import re

import thread
import threading
import random
import shutil
import textwrap
import logging
import logging.config
from pycocotools import mask
from multiprocessing import Process, Manager

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),"../storage"))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),"../utils"))

from jobs_tensorboard import GenTensorboardMeta
import k8sUtils

from config import config
from DataHandler import DataHandler

from cluster_manager import setup_exporter_thread, manager_iteration_histogram, register_stack_trace_dump, update_file_modification_time

logger = logging.getLogger(__name__)

def PolygonArea(corners):
    n = len(corners) # of corners
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += corners[i][0] * corners[j][1]
        area -= corners[j][0] * corners[i][1]
    area = abs(area) / 2.0
    return area
def segmentationToCorner(segmentation):
    tmp = []
    for i in range(0,len(segmentation),2):
        tmp.append([segmentation[i],segmentation[i+1]])
    return tmp

def create_log(logdir = '/var/log/dlworkspace'):
    if not os.path.exists(logdir):
        os.system("mkdir -p " + logdir)
    with open('logging.yaml') as f:
        logging_config = yaml.load(f)
        f.close()
        logging_config["handlers"]["file"]["filename"] = logdir+"/dataconvert.log"
        logging.config.dictConfig(logging_config)

def insert_status_to_dataset(datasetId,projectId,status,out_path=None):
    dataset_info_path = os.path.join(config["data_platform_path"],"private/account/%s/membership.json" % (projectId))
    with open(dataset_info_path,"r") as f:
        infos = json.loads(f.read())
    if "dataSets" in infos:
        if datasetId in infos["dataSets"]:
            one_info = infos["dataSets"][datasetId]
            if "convertStatus" in one_info:
                logging.info("dataset: %s %s update status again!" % (projectId,datasetId))
            one_info["convertStatus"] = status
            one_info["convertOutPath"] = out_path
            with open(dataset_info_path,"w") as f:
                f.write(json.dumps(infos,indent=4, separators=(',', ':')))

def mkdirs(path):
    if not os.path.exists(path):
        os.makedirs(path)

index = 0
def merge_json_to_coco_dataset(list_ppath,json_path,coco_file_path,prefix="",args=None,category_path=None):
    coco = {}
    coco["images"] = []
    coco["categories"] = []
    coco["annotations"] = []
    with open(os.path.join(list_ppath, "list.json"), "r") as f:
        data = json.load(f)
        ImgIDs = data.get("ImgIDs",[])
        suffixs = data.get("suffixs",[])
    categories = {}
    categories_total = None
    if os.path.exists(category_path):
        with open(category_path, "r") as f2:
            categories_total = json.load(f2)["categories"]
    for index,ImgID in enumerate(ImgIDs):
        new_image_id = ImgID
        anno_path = os.path.join(json_path, 'images', "{}.json".format(ImgID))
        if not os.path.exists(anno_path):

            # compatible with image.suffix.json
            new_anno_path = os.path.join(json_path, 'images', "{}{}.json".format(ImgID,suffixs[index]))
            if os.path.exists(new_anno_path):
                anno_path = new_anno_path
            else:
                continue
        with open(anno_path, "r") as f:
            json_dict = json.load(f)
        json_dict["images"][0]["file_name"] = "{}.jpg".format(new_image_id)
        json_dict["images"][0]["id"] = new_image_id
        if json_dict.get("categories"):
            categories_total = json_dict.get("categories")
        for i in json_dict["annotations"]:
            i["image_id"] = new_image_id
            global index
            i["id"] = index
            index += 1
            if i["category_id"] not in categories:
                categories[i["category_id"]] = {"id":i["category_id"],"name":i["category_id"],"supercategory":i["category_id"]}
                if "category_name" in i:
                    categories[i["category_id"]]["name"] = i["category_name"]
                if "supercategory" in i:
                    categories[i["category_id"]]["supercategory"] = i["supercategory"]
            if categories_total:
                categories[i["category_id"]]["name"] = categories_total[i["category_id"]-1]["name"]
                categories[i["category_id"]]["supercategory"] = categories_total[i["category_id"]-1]["supercategory"]
            if "area" not in i:
                if i["segmentation"]:
                    i["area"] = int(PolygonArea(segmentationToCorner((i["segmentation"][0]))))
                if i["bbox"]:
                    i["area"] = i["bbox"][2] * i["bbox"][3]
            if "iscrowd" not in i:
                i["iscrowd"] = 0
        coco["images"].extend(json_dict["images"])
        coco["annotations"].extend(json_dict["annotations"])
        # source_path = os.path.join(json_path, 'images', "{}.jpg".format(ImgID))
        # if args and not args.ignore_image:
        #     shutil.copyfile(source_path, os.path.join(coco_image_path, "{}.jpg".format(new_image_id)))
    coco["categories"] = list(map(lambda x:x[1],sorted([[k,v] for k,v in categories.items()],key=lambda x:x[0])))
    with open(coco_file_path, "w") as f:
        f.write(json.dumps(coco, indent=4, separators=(',', ':')))
    with open(os.path.join(os.path.dirname(coco_file_path),"class_names.json"), "w") as f:
        f.write(json.dumps(coco["categories"], indent=4, separators=(',', ':')))


def judge_datasets_is_private(projectId,datasetId):
    ret = False
    path = os.path.join(config["data_platform_path"], "private/account/%s/membership.json" % (projectId))
    if os.path.exists(path):
        with open(path, "r") as f:
            infos = json.loads(f.read())
        ret = infos["dataSets"][datasetId]["isPrivate"]
    return ret

def find_dataset_creator(projectId):
    path = os.path.join(config["data_platform_path"], "private/account/index.json")
    with open(path, "r") as f:
        infos = json.loads(f.read())
    creator = infos[projectId]["creator"]
    return creator

def find_dataset_bind_path(projectId,datasetId,isPrivate=False):
    path = os.path.join(config["data_platform_path"], "private/account/%s/membership.json" % (projectId))
    with open(path, "r") as f:
        infos = json.loads(f.read())
    ret = infos["dataSets"][datasetId]["dataSetPath"]
    # return re.sub("^/data", "/dlwsdata/storage",ret) if not isPrivate else re.sub("^/home", "/dlwsdata/work",ret)
    return ret

def DoDataConvert():
    dataHandler = DataHandler()
    jobs = dataHandler.getConvertList(targetStatus="queued")
    for oneJob in jobs:
        if oneJob["type"] == "image" and oneJob["targetFormat"]=="coco":
            try:
                list_path = os.path.join(config["data_platform_path"], "public/tasks/%s" % (oneJob["datasetId"]))
                json_path = os.path.join(config["data_platform_path"], "private/tasks/%s/%s" % (oneJob["datasetId"], oneJob["projectId"]))
                category_path = os.path.join(config["data_platform_path"], "private/tasks/%s/%s/category.json" % (oneJob["datasetId"],oneJob["projectId"]))
                if judge_datasets_is_private(oneJob["projectId"],oneJob["datasetId"]):
                    username =find_dataset_creator(oneJob["projectId"])
                    coco_base_path = os.path.join(config["storage-mount-path"], "work/%s/data_platform/%s/%s/format_coco" % (username,oneJob["projectId"],oneJob["datasetId"]))
                    coco_file_path = os.path.join(coco_base_path, "annotations/instance.json")
                    show_coco_file_path = "/home/%s/data_platform/%s/%s" % (username,oneJob["projectId"],oneJob["datasetId"])
                    mkdirs(os.path.dirname(coco_file_path))
                    os.system("ln -s %s %s" %(find_dataset_bind_path(oneJob["projectId"],oneJob["datasetId"],isPrivate=True),os.path.join(coco_base_path,"images")))
                else:
                    coco_base_path = os.path.join(config["storage-mount-path"],"storage/data_platform/%s/%s/format_coco" % (oneJob["projectId"],oneJob["datasetId"]))
                    coco_file_path = os.path.join(coco_base_path,"annotations/instance.json")
                    show_coco_file_path = "/data/data_platform/%s/%s" % (oneJob["projectId"],oneJob["datasetId"])
                    mkdirs(os.path.dirname(coco_file_path))
                    os.system("ln -s %s %s" % (find_dataset_bind_path(oneJob["projectId"],oneJob["datasetId"]), os.path.join(coco_base_path,"images")))
                logging.info("=============start convert to format %s" % (oneJob["targetFormat"]))
                merge_json_to_coco_dataset(list_path,json_path,coco_file_path,category_path=category_path)
                dataHandler.updateConvertStatus("finished",oneJob["id"],coco_file_path)
                insert_status_to_dataset(oneJob["datasetId"], oneJob["projectId"],"finished",show_coco_file_path)
                logging.info("=============convert to format %s done" % (oneJob["targetFormat"]))
            except Exception as e:
                logging.exception(e)
                dataHandler.updateConvertStatus("error", oneJob["id"],e)
                insert_status_to_dataset(oneJob["datasetId"], oneJob["projectId"],"error")

def Run():
    register_stack_trace_dump()
    create_log()
    logger.info("start to DoDataConvert...")

    while True:
        update_file_modification_time("DataConvert")

        with manager_iteration_histogram.labels("data_convert").time():
            try:
                DoDataConvert()
            except Exception as e:
                logger.exception("do dataConvert failed")
        time.sleep(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", "-p", help="port of exporter", type=int, default=9209)
    args = parser.parse_args()
    setup_exporter_thread(args.port)

    Run()
