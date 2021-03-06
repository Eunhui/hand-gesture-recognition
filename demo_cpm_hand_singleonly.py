# For single hand and no body part in the picture
# DEMO_TYPE SINGLE only / WEBCAM only / RGB only
# ======================================================

import tensorflow as tf
from models.nets import cpm_hand_slim
import numpy as np
from utils import cpm_utils
import cv2
import time
import math
import sys
import json
from primesense import openni2
from primesense import _openni2 as c_api

"""Parameters
"""
FLAGS = tf.app.flags.FLAGS
tf.app.flags.DEFINE_string('model_path',
                           default_value='models/weights/cpm_hand.pkl',
                           docstring='Your model')
tf.app.flags.DEFINE_integer('input_size',
                            default_value=368,
                            docstring='Input image size')
tf.app.flags.DEFINE_integer('hmap_size',
                            default_value=46,
                            docstring='Output heatmap size')
tf.app.flags.DEFINE_integer('cmap_radius',
                            default_value=21,
                            docstring='Center map gaussian variance')
tf.app.flags.DEFINE_integer('joints',
                            default_value=21,
                            docstring='Number of joints')
tf.app.flags.DEFINE_integer('stages',
                            default_value=6,
                            docstring='How many CPM stages')
tf.app.flags.DEFINE_integer('cam_num',
                            default_value=0,
                            docstring='Webcam device number')
tf.app.flags.DEFINE_bool('KALMAN_ON',
                         default_value=True,
                         docstring='enable kalman filter')
tf.app.flags.DEFINE_float('kalman_noise',
                            default_value=3e-2,
                            docstring='Kalman filter noise value')
tf.app.flags.DEFINE_bool('WRITE_JSON',
                         default_value=True,
                         docstring='enable json write')

# Set color for each finger
joint_color_code = [[139, 53, 255],
                    [0, 56, 255],
                    [43, 140, 237],
                    [37, 168, 36],
                    [147, 147, 0],
                    [70, 17, 145]]


limbs = [[0, 1],
         [1, 2],
         [2, 3],
         [3, 4],
         [0, 5],
         [5, 6],
         [6, 7],
         [7, 8],
         [0, 9],
         [9, 10],
         [10, 11],
         [11, 12],
         [0, 13],
         [13, 14],
         [14, 15],
         [15, 16],
         [0, 17],
         [17, 18],
         [18, 19],
         [19, 20]
         ]

if sys.version_info.major == 3:
    PYTHON_VERSION = 3
else:
    PYTHON_VERSION = 2

def main(argv):
    tf_device = '/gpu:0'
    with tf.device(tf_device):
        """Build graph
        """

    frame_num = 0

    input_data = tf.placeholder(dtype=tf.float32, shape=[None, FLAGS.input_size, FLAGS.input_size, 3],
                                        name='input_image')
    center_map = tf.placeholder(dtype=tf.float32, shape=[None, FLAGS.input_size, FLAGS.input_size, 1],
                                    name='center_map')

    model = cpm_hand_slim.CPM_Model(FLAGS.stages, FLAGS.joints + 1)
    model.build_model(input_data, center_map, 1)

    """Create session and restore weights
    """
    sess = tf.Session()

    sess.run(tf.global_variables_initializer())
    model.load_weights_from_file(FLAGS.model_path, sess, False)
    
    test_center_map = cpm_utils.gaussian_img(FLAGS.input_size, FLAGS.input_size, FLAGS.input_size / 2,
                                             FLAGS.input_size / 2,
                                             FLAGS.cmap_radius)
    test_center_map = np.reshape(test_center_map, [1, FLAGS.input_size, FLAGS.input_size, 1])

    # Check weights
    for variable in tf.trainable_variables():
        with tf.variable_scope('', reuse=True):
            var = tf.get_variable(variable.name.split(':0')[0])
            print(variable.name, np.mean(sess.run(var)))

    cam = cv2.VideoCapture(FLAGS.cam_num)

    # Create kalman filters
    if FLAGS.KALMAN_ON:
        kalman_filter_array = [cv2.KalmanFilter(4, 2) for _ in range(FLAGS.joints)]
        for _, joint_kalman_filter in enumerate(kalman_filter_array):
            joint_kalman_filter.transitionMatrix = np.array([[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]],
                                                            np.float32)
            joint_kalman_filter.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], np.float32)
            joint_kalman_filter.processNoiseCov = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                                                           np.float32) * FLAGS.kalman_noise
    else:
        kalman_filter_array = None

    # Init Openni2
    openni2.initialize("C:\OpenNI\Redist")
    dev = openni2.Device.open_any()
    depth_stream = dev.create_depth_stream()
    depth_stream.start()
    depth_stream.set_video_mode(
        c_api.OniVideoMode(pixelFormat=c_api.OniPixelFormat.ONI_PIXEL_FORMAT_DEPTH_100_UM, resolutionX=640,
                           resolutionY=480, fps=30))

    with tf.device(tf_device):

        while True:
            # t1 = time.time()
            orig_img, test_img, depth_map, hand = cpm_utils.read_image(cam, FLAGS.input_size, depth_stream)

            test_img_resize = cv2.resize(test_img, (FLAGS.input_size, FLAGS.input_size))
            # print('img read time %f' % (time.time() - t1))

            test_img_input = test_img_resize / 256.0 - 0.5
            test_img_input = np.expand_dims(test_img_input, axis=0)

            # Inference
            t1 = time.time()
            stage_heatmap_np = sess.run([model.stage_heatmap[5]],
                                            feed_dict={'input_image:0': test_img_input,
                                                       'center_map:0': test_center_map})

            # Show visualized image
            demo_img = visualize_result(test_img, orig_img, FLAGS, stage_heatmap_np, kalman_filter_array, frame_num, depth_map)
            cv2.imshow('org img', orig_img)
            cv2.imshow('processed img', test_img)
            cv2.imshow('current depth', depth_map)
            cv2.imshow('hand depth only', hand)
            cv2.imshow('current heatmap', demo_img.astype(np.uint8))
            if cv2.waitKey(1) == ord('q'): break
            print('fps: %.2f' % (1 / (time.time() - t1)))
            print(frame_num)
            frame_num = frame_num + 1


def visualize_result(test_img, orig_img, FLAGS, stage_heatmap_np, kalman_filter_array, num, dep_map):
    # t1 = time.time()
    last_heatmap = stage_heatmap_np[len(stage_heatmap_np) - 1][0, :, :, 0:FLAGS.joints].reshape(
        (FLAGS.hmap_size, FLAGS.hmap_size, FLAGS.joints))
    last_heatmap = cv2.resize(last_heatmap, (test_img.shape[1], test_img.shape[0]))
    # print('hm resize time %f' % (time.time() - t1))

    t1 = time.time()
    joint_coord_set = np.zeros((FLAGS.joints, 2))

    # Plot joint colors
    if kalman_filter_array is not None:
        for joint_num in range(FLAGS.joints):
            joint_coord = np.unravel_index(np.argmax(last_heatmap[:, :, joint_num]),
                                           (test_img.shape[0], test_img.shape[1]))
            joint_coord = np.array(joint_coord).reshape((2, 1)).astype(np.float32)
            kalman_filter_array[joint_num].correct(joint_coord)
            kalman_pred = kalman_filter_array[joint_num].predict()
            joint_coord_set[joint_num, :] = np.array([kalman_pred[0], kalman_pred[1]]).reshape((2))

            color_code_num = (joint_num // 4)
            if joint_num in [0, 4, 8, 12, 16]:
                if PYTHON_VERSION == 3:
                    joint_color = list(map(lambda x: x + 35 * (joint_num % 4), joint_color_code[color_code_num]))
                else:
                    joint_color = map(lambda x: x + 35 * (joint_num % 4), joint_color_code[color_code_num])

                cv2.circle(test_img, center=(joint_coord[1], joint_coord[0]), radius=3, color=joint_color, thickness=-1)
            else:
                if PYTHON_VERSION == 3:
                    joint_color = list(map(lambda x: x + 35 * (joint_num % 4), joint_color_code[color_code_num]))
                else:
                    joint_color = map(lambda x: x + 35 * (joint_num % 4), joint_color_code[color_code_num])

                cv2.circle(test_img, center=(joint_coord[1], joint_coord[0]), radius=3, color=joint_color, thickness=-1)
    else:
        for joint_num in range(FLAGS.joints):
            joint_coord = np.unravel_index(np.argmax(last_heatmap[:, :, joint_num]),
                                           (test_img.shape[0], test_img.shape[1]))
            joint_coord_set[joint_num, :] = [joint_coord[0], joint_coord[1]]

            color_code_num = (joint_num // 4)
            if joint_num in [0, 4, 8, 12, 16]:
                if PYTHON_VERSION == 3:
                    joint_color = list(map(lambda x: x + 35 * (joint_num % 4), joint_color_code[color_code_num]))
                else:
                    joint_color = map(lambda x: x + 35 * (joint_num % 4), joint_color_code[color_code_num])

                cv2.circle(test_img, center=(joint_coord[1], joint_coord[0]), radius=3, color=joint_color, thickness=-1)
            else:
                if PYTHON_VERSION == 3:
                    joint_color = list(map(lambda x: x + 35 * (joint_num % 4), joint_color_code[color_code_num]))
                else:
                    joint_color = map(lambda x: x + 35 * (joint_num % 4), joint_color_code[color_code_num])

                cv2.circle(test_img, center=(joint_coord[1], joint_coord[0]), radius=3, color=joint_color, thickness=-1)
    # print('plot joint time %f' % (time.time() - t1))

    # t1 = time.time()
    # Plot limb colors
    for limb_num in range(len(limbs)):
        x1 = joint_coord_set[limbs[limb_num][0], 0]
        y1 = joint_coord_set[limbs[limb_num][0], 1]
        x2 = joint_coord_set[limbs[limb_num][1], 0]
        y2 = joint_coord_set[limbs[limb_num][1], 1]
        length = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
        if length < 150 and length > 5:
            deg = math.degrees(math.atan2(x1 - x2, y1 - y2))
            polygon = cv2.ellipse2Poly((int((y1 + y2) / 2), int((x1 + x2) / 2)),
                                       (int(length / 2), 3),
                                       int(deg),
                                       0, 360, 1)
            color_code_num = limb_num // 4
            if PYTHON_VERSION == 3:
                limb_color = list(map(lambda x: x + 35 * (limb_num % 4), joint_color_code[color_code_num]))
            else:
                limb_color = map(lambda x: x + 35 * (limb_num % 4), joint_color_code[color_code_num])

            cv2.fillConvexPoly(test_img, polygon, color=limb_color)
    # print('plot limb time %f' % (time.time() - t1))

    if FLAGS.WRITE_JSON:
        # Get JSON file data
        json_data = []
        for i in range(0, 21):
            joint_x = joint_coord_set[i, 0]
            joint_y = joint_coord_set[i, 1]
            if joint_x <= FLAGS.input_size and joint_y <= FLAGS.input_size:
                depth_joint = int(dep_map[int(joint_x) - 1][int(joint_y) - 1][0])
            else:
                depth_joint = 0
            json_data.extend([joint_x, joint_y, depth_joint])

        # Extract to JSON file
        json_title = 'json/test_' + str(num).zfill(8) + '.json'
        with open(json_title, 'w+', encoding="utf-8") as make_file:
            json.dump(json_data, make_file, ensure_ascii=False, indent='\t')

    return test_img


if __name__ == '__main__':
    tf.app.run()

