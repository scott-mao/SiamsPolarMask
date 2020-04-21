# -*- coding: utf-8 -*-
"""jinxin.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1MNnNFXuYRlnCyH-zJLpWSSYGMQrarY08
"""

import torch
import torch.utils.data as data
from pycocotools.coco import COCO
import numpy as np
import cv2
from PIL import Image, ImageOps, ImageStat, ImageDraw
import os
import os.path as osp


class COCODataset(data.Dataset):
    def __init__(self, annFilePath, imgDir, catId=1, transform=None):
        super(COCODataset, self).__init__()
        self.annFilePath = annFilePath
        self.imgDir = imgDir
        self.catId = catId
        self.transform = transform
        # annFile = '../../504Proj/annotations/instances_val2017.json'
        self.coco = COCO(annFilePath)
        self.imgIds = self.coco.getImgIds(catIds=self.catId)
        #self.tmp_dir = '../check'

    def __getitem__(self, index):
        meta = {}
        img_info = self.coco.loadImgs(self.imgIds[index])[0]
        img = Image.open(osp.join(self.imgDir, img_info['file_name']))
        annIds = self.coco.getAnnIds(imgIds=img_info['id'], catIds=self.catId, iscrowd=False)
        anns = self.coco.loadAnns(annIds)
        max_area_ann = max(anns, key=lambda x: x['area'])    # ann ID
        bbox = max_area_ann['bbox']

        meta['template'], meta['detection'], meta['cords_of_bbox_in_detection'], max_area_ann['segmentation'] = self.transform_cords(img, bbox, max_area_ann['segmentation'])

        t = self.coco.imgs[max_area_ann['image_id']]
        t['height'], t['width'] = 255, 255
        mask = self.coco.annToMask(max_area_ann)

        c_x = np.mean(mask.nonzero()[0])            # numpy 下的x, y坐标 与opencv相反
        c_y = np.mean(mask.nonzero()[1])
        center = np.array([c_x, c_y]) #torch.Tensor([c_x, c_y])

        ##################################################
        # TODO
        # 添加中心点周围8个点坐标及其对应边界点
        # 考虑中心点在边界的情况
        # 输入与输出的坐标变换公式为 p_in = 8p_out + 31
        # 具体分为两个阶段 第一阶段 p_in = 8p_backbone + 7 第二阶段 p_backbone = p_out + 3
        f_cx = round(max(0, (c_x - 31) / 8))
        f_cy = round(max(0, (c_y - 31) / 8))

        valid_centers = self.get_valid_center_from_fm(25, f_cx, f_cy)
        
        gt_class = self.gen_gt_class(25, valid_centers)

        valid_centers_in_ori = self.coord_transform(valid_centers, 'f2o')
        ##################################################
        # TODO
        # 添加中心点周围8个点坐标及其对应边界点
        # 考虑中心点在边界的情况
        # 输入与输出的坐标变换公式为 p_in = 8p_out + 31
        # 具体分为两个阶段 第一阶段 p_in = 8p_backbone + 7 第二阶段 p_backbone = p_out + 3
        ##################################################

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        contours = np.concatenate(contours)          # size: n * 1 * 2
        contours = contours.reshape(-1, 2)           # 此处为opencv的x, y坐标，后处理需要交换

        distances = []
        new_coordinates = []
        for c in valid_centers_in_ori:
          print(c)
          dst, new_coord = self.get_36_coordinates(c[0][0], c[0][1], contours)  # distance is a list, new_coord is a dictionary which keys are angles(0 ~ 360, 10)
          distances.append(dst.reshape((1,-1)))
          new_coordinates.append(new_coord)

        #distances = torch.Tensor(distances)
        #new_coordinates = torch.Tensor(new_coordinates)

        distances = torch.cat(distances[:], 0)

        distance, new_coord = self.get_36_coordinates(c_x, c_y, contours)
        ####################################################
        # TODO
        # Transform image

        # meta['image'] = self.transform(img)
        #if img is not None:
        #  meta['template'], meta['detection'], meta['bbox'], meta['center'], meta['distance'] = self.transform_inf(img, bbox, center, distance)
        #self.transform(img, bbox, center, distance)
        ####################################################
        meta['id'] = max_area_ann['id']
        meta['imgId'] = max_area_ann['image_id']
        #meta['bbox'] = bbox
        meta['center'] = center
        meta['distance'] = distance
        meta['coords'] = new_coord
        meta['targets'] = {
            'distances': distances,
            'gt_class': gt_class,
        }
        meta['valid_centers'] = valid_centers
        #meta['mask'] = torch.Tensor(mask).resize((255, 255))

        return meta


    def __len__(self):
        return len(self.imgIds)

    def get_36_coordinates(self, c_x, c_y, pos_mask_contour):
        # 输入为opencv坐标系下的contuor， 在计算时转化为Numpy下的坐标
        ct = pos_mask_contour
        x = torch.Tensor(ct[:, 1] - c_x)      # opencv x, y交换
        y = torch.Tensor(ct[:, 0] - c_y)

        angle = torch.atan2(x, y) * 180 / np.pi
        angle[angle < 0] += 360
        angle = angle.int()
        # dist = np.sqrt(x ** 2 + y ** 2)
        dist = torch.sqrt(x ** 2 + y ** 2)
        angle, idx = torch.sort(angle)
        dist = dist[idx]
        ct2 = ct[idx]

        # 生成36个角度
        new_coordinate = {}
        for i in range(0, 360, 10):
            if i in angle:
                d = dist[angle == i].max()
                new_coordinate[i] = d
            elif i + 1 in angle:
                d = dist[angle == i + 1].max()
                new_coordinate[i] = d
            elif i - 1 in angle:
                d = dist[angle == i - 1].max()
                new_coordinate[i] = d
            elif i + 2 in angle:
                d = dist[angle == i + 2].max()
                new_coordinate[i] = d
            elif i - 2 in angle:
                d = dist[angle == i - 2].max()
                new_coordinate[i] = d
            elif i + 3 in angle:
                d = dist[angle == i + 3].max()
                new_coordinate[i] = d
            elif i - 3 in angle:
                d = dist[angle == i - 3].max()
                new_coordinate[i] = d

        distances = torch.zeros(36)

        for a in range(0, 360, 10):
            if not a in new_coordinate.keys():
                new_coordinate[a] = torch.tensor(1e-6)
                distances[a // 10] = 1e-6
            else:
                distances[a // 10] = new_coordinate[a]
        # for idx in range(36):
        #     dist = new_coordinate[idx * 10]
        #     distances[idx] = dist

        return distances, new_coordinate
    def get_valid_center_from_fm(self, fm_size, c_x, c_y):
        valid_centers = []
        for i in range(-1, 2):
          for j in range(-1, 2):
            #print(c_x + i, c_y + j)
            if c_x + i in range(0, fm_size) and c_y + j in range(0, fm_size):
              valid_centers.append(torch.Tensor((c_x + i, c_y + j)).reshape((1,2)))
        return valid_centers

    def gen_gt_class(self, fm_size, valid_centers):
        gt_class = np.zeros((fm_size, fm_size))
        for c in valid_centers:
          gt_class[int(c[0][0]), int(c[0][1])] = 1
        return torch.Tensor(gt_class)

    def coord_transform(self, coords, mode='f2o'):
        new_coords = []
        if mode == 'f2o':
          for c in coords:
            new_coords.append(8 * c + 31)
        elif mode == 'o2f':
          for c in coords:
            new_coords.append(round((c - 31) / 8))
        return new_coords

    def transform_cords(self, image, bbox, segmentation_in_original_image):
        mean_template_and_detection = tuple(map(round, ImageStat.Stat(image).mean))
        bbox_xywh = np.array([bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2, bbox[2], bbox[3]],
                             np.float32)  # 将标注ann中的bbox从左上点的坐标+bbox长宽 -> 中心点的坐标+bbox的长宽
        bbox_x1y1x2y2 = np.array([bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3]],
                                 np.float32)  # 将标注ann中的bbox从左上点的坐标+bbox长宽 -> 左上点的坐标+右下点的坐标

        original_image_w, original_image_h = image.size
        cx, cy, tw, th = bbox_xywh
        p = round((tw + th) / 2, 2)
        template_square_size = int(np.sqrt((tw + p) * (th + p)))  # a
        detection_square_size = int(template_square_size * 2)  # A = 2a

        # pad
        detection_lt_x, detection_lt_y = cx - detection_square_size // 2, cy - detection_square_size // 2
        detection_rb_x, detection_rb_y = cx + detection_square_size // 2, cy + detection_square_size // 2
        left = -detection_lt_x if detection_lt_x < 0 else 0
        top = -detection_lt_y if detection_lt_y < 0 else 0
        right = detection_rb_x - original_image_w if detection_rb_x > original_image_w else 0
        bottom = detection_rb_y - original_image_h if detection_rb_y > original_image_h else 0
        padding = tuple(map(int, [left, top, right, bottom]))
        padding_image_w, padding_image_h = left + right + original_image_w, top + bottom + original_image_h

        template_img_padding = ImageOps.expand(image, border=padding, fill=mean_template_and_detection)
        detection_img_padding = ImageOps.expand(image, border=padding, fill=mean_template_and_detection)

        # crop
        tl = cx + left - template_square_size // 2
        tt = cy + top - template_square_size // 2
        tr = padding_image_w - tl - template_square_size
        tb = padding_image_h - tt - template_square_size
        template_img_crop = ImageOps.crop(template_img_padding.copy(), (tl, tt, tr, tb))

        dl = np.clip(cx + left - detection_square_size // 2, 0, padding_image_w - detection_square_size)
        dt = np.clip(cy + top - detection_square_size // 2, 0, padding_image_h - detection_square_size)
        dr = np.clip(padding_image_w - dl - detection_square_size, 0, padding_image_w - detection_square_size)
        db = np.clip(padding_image_h - dt - detection_square_size, 0, padding_image_h - detection_square_size)
        detection_img_crop = ImageOps.crop(detection_img_padding.copy(), (dl, dt, dr, db))

        detection_tlcords_of_original_image = (cx - detection_square_size // 2, cy - detection_square_size // 2)
        detection_rbcords_of_original_image = (cx + detection_square_size // 2, cy + detection_square_size // 2)

        detection_tlcords_of_padding_image = (
        cx - detection_square_size // 2 + left, cy - detection_square_size // 2 + top)
        detection_rbcords_of_padding_image = (
        cx + detection_square_size // 2 + left, cy + detection_square_size // 2 + top)

        # resize
        template_img_resized = template_img_crop.copy().resize((127, 127))
        detection_img_resized = detection_img_crop.copy().resize((256, 256))

        template_resized_ratio = round(127 / template_square_size, 2)
        detection_resized_ratio = round(256 / detection_square_size, 2)

        segmentation_in_padding_img = segmentation_in_original_image
        for i in range(len(segmentation_in_original_image)):
            for j in range(len(segmentation_in_original_image[i]) // 2):
                segmentation_in_padding_img[i][2 * j] = segmentation_in_original_image[i][2 * j] + top  # left
                segmentation_in_padding_img[i][2 * j + 1] = segmentation_in_original_image[i][2 * j + 1] + left  # top

        x11, y11 = detection_tlcords_of_padding_image
        x12, y12 = detection_rbcords_of_padding_image

        segmentation_in_cropped_img = segmentation_in_padding_img
        for i in range(len(segmentation_in_padding_img)):
            for j in range(len(segmentation_in_padding_img[i]) // 2):
                segmentation_in_cropped_img[i][2 * j] = segmentation_in_padding_img[i][2 * j] - x11
                segmentation_in_cropped_img[i][2 * j + 1] = segmentation_in_padding_img[i][2 * j + 1] - y11
                segmentation_in_cropped_img[i][2 * j] = np.clip(segmentation_in_cropped_img[i][2 * j], 0,
                                                                x12 - x11).astype(np.float32)
                segmentation_in_cropped_img[i][2 * j + 1] = np.clip(segmentation_in_cropped_img[i][2 * j + 1], 0,
                                                                    y12 - y11).astype(np.float32)

        segmentation_in_detection = segmentation_in_cropped_img
        for i in range(len(segmentation_in_cropped_img)):
            for j in range(len(segmentation_in_cropped_img[i])):
                segmentation_in_detection[i][j] = segmentation_in_cropped_img[i][j] * detection_resized_ratio

        blcords_of_bbox_in_padding_image, btcords_of_bbox_in_padding_image, brcords_of_bbox_in_padding_image, bbcords_of_bbox_in_padding_image = \
        bbox_x1y1x2y2[0] + left, bbox_x1y1x2y2[1] + top, bbox_x1y1x2y2[2] + left, bbox_x1y1x2y2[3] + top
        blcords_of_bbox_in_detection, btcords_of_bbox_in_detection, brcords_of_bbox_in_detection, bbcords_of_bbox_in_detection = blcords_of_bbox_in_padding_image - x11, btcords_of_bbox_in_padding_image - y11, brcords_of_bbox_in_padding_image - x11, bbcords_of_bbox_in_padding_image - y11
        x1 = np.clip(blcords_of_bbox_in_detection, 0, x12 - x11).astype(np.float32)
        y1 = np.clip(btcords_of_bbox_in_detection, 0, y12 - y11).astype(np.float32)
        x2 = np.clip(brcords_of_bbox_in_detection, 0, x12 - x11).astype(np.float32)
        y2 = np.clip(bbcords_of_bbox_in_detection, 0, y12 - y11).astype(np.float32)
        cords_of_bbox_in_cropped_detection = np.array([x1, y1, x2, y2], dtype=np.float32)
        cords_of_bbox_in_resized_detection = cords_of_bbox_in_cropped_detection * detection_resized_ratio
        # print('distance',distances)
        # print(template_img_resized, detection_img_resized, cords_of_bbox_in_resized_detection, cords_of_center_in_resized_detection, distances)
        # template_img_resized.save(osp.join(self.tmp_dir, 'template_img_resized.jpg'))
        # detection_img_resized.save(osp.join(self.tmp_dir, 'detection_img_resized.jpg'))
        # detection_img_resized_copy1 = detection_img_resized.copy()
        # draw = ImageDraw.Draw(detection_img_resized_copy1)
        # x1, y1, x2, y2 = cords_of_bbox_in_resized_detection
        # draw.line([(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)], width=1, fill='red') #bbox in resized detection image
        # detection_img_resized_copy1.save(osp.join(self.tmp_dir, 'bbox_in_detection_img_resized.jpg'))

        # detection_img_resized_copy2 = detection_img_resized.copy()
        # draw = ImageDraw.Draw(detection_img_resized_copy2)
        # for angle in range(len(distances)):
        #  #print(distances[i]*np.sin(angle/18 *np.pi))
        #  #print(distances[i]*np.cos(angle/18 *np.pi))
        #  draw.line([(cords_of_center_in_resized_detection[0], cords_of_center_in_resized_detection[1]), (cords_of_center_in_resized_detection[0]+distances[angle]*np.cos(angle/18 *np.pi),cords_of_center_in_resized_detection[1]+distances[angle]*np.sin(angle/18 *np.pi))], width=1, fill='red')
        # detection_img_resized_copy2.save(osp.join(self.tmp_dir, 'polarmask_in_detection_img_resized.jpg'))
        return (template_img_resized, detection_img_resized, cords_of_bbox_in_resized_detection, segmentation_in_detection)


# if __name__ == '__main__':
#     annFile = '../annotations/instances_val2017.json'
#     imgDir = '../val2017'
#     mean = [0.471, 0.448, 0.408]
#     std = [0.234, 0.239, 0.242]
#     img_transforms = transforms.Compose([
#         transforms.ToTensor(),
#         transforms.Normalize(mean, std)
#     ])
#     # coco =  COCO(annFile)
#     # max_area_ann ={'segmentation': [[39.485, 256.28, 15.317199602127076, 256.28, 1.1323999857902527, 256.28, 0.35759999200701714, 256.28, 19.921299829483033, 256.28, 32.586301250457765, 256.28, 39.09759965896606, 256.28, 44.863900909423826, 256.28, 45.23640090942383, 256.28, 45.23640090942383, 256.28, 44.476500568389895, 256.28, 42.55439920425415, 256.28, 41.79449886322021, 256.28], [0.0, 306.96, 5.65, 311.33, 7.71, 321.63, 8.22, 330.38, 8.99, 337.08, 7.96, 339.14, 6.16, 341.2, 0.24, 342.74]], 'area': 516.8099500000006, 'iscrowd': 0, 'image_id': 42070, 'bbox': [0.0, 306.96, 30.36, 56.89], 'category_id': 1, 'id': 1728146}
#     #
#     # t = coco.imgs[max_area_ann['image_id']]
#     # t['height'], t['width'] = 255, 255
#     # mask = coco.annToMask(max_area_ann)
#     # print(mask.shape)
#     # c_x = np.mean(mask.nonzero()[0])  # numpy 下的x, y坐标 与opencv相反
#     # c_y = np.mean(mask.nonzero()[1])
#     # print(c_x,c_y)
#     # contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
#     # contours = np.concatenate(contours)  # size: n * 1 * 2
#     # contours = contours.reshape(-1, 2)
#     # exit()
#     train_data = COCODataset(annFilePath=annFile, imgDir=imgDir, transforms = img_transforms)
#     train_loader = data.DataLoader(dataset=train_data, batch_size=5, shuffle=False)
#
#     def get_contours_from_polar(cx, cy, polar_coords):
#         new_coords = []
#         for angle, dst in polar_coords.items():
#             x = cx + dst * np.sin(angle * np.pi / 180)
#             y = cy + dst * np.cos(angle * np.pi / 180)
#             new_coords.append([x, y])
#         return new_coords
#
#
#
#
# annFile = '../instances_val2017.json'
# imgDir = '../val2017'
# train_data = COCODataset(annFilePath=annFile, imgDir=imgDir)
# train_loader = data.DataLoader(dataset=train_data, batch_size=5, shuffle=False)
#
# for i, Data in enumerate(train_loader):
#     if i > 0:
#         break
#     print(Data['id'])