from rockstar import RockStar

python_code = " # TODO: update the readme with new parameters
# TODO: restoring a model without recreating it (use constants / op names in the code?)
# TODO: move all the training parameters inside the training parser
# TODO: switch to https://www.tensorflow.org/api_docs/python/tf/nn/dynamic_rnn instead of buckets

from __future__ import absolute_import
import sys
import cv2
import argparse
import logging
import os
import shutil
import tensorflow as tf

from model import Model
from defaults import Config
import dataset
from data_gen import DataGen
from export import Exporter
import numpy as np
from os import makedirs

tf.logging.set_verbosity(tf.logging.ERROR)


def process_args(args, defaults):

    parser = argparse.ArgumentParser()
    parser.prog = 'aocr'
    subparsers = parser.add_subparsers()

    # Global arguments
    parser_base = argparse.ArgumentParser(add_help=False)
    parser_base.add_argument('--log-path', dest="log_path",
                             metavar=defaults.LOG_PATH,
                             type=str, default=defaults.LOG_PATH,
                             help=('log file path (default: %s)'
                                   % (defaults.LOG_PATH)))

    # Dataset generation
    parser_dataset = subparsers.add_parser('dataset', parents=[parser_base],
                                           help='create a dataset in the TFRecords format')
    parser_dataset.set_defaults(phase='dataset')
    parser_dataset.add_argument('annotations_path', metavar='annotations',
                                                            type=str,
                                                            help=('path to the annotation file'))
    parser_dataset.add_argument('output_path', nargs='?', metavar='output',
                                type=str, default=defaults.NEW_DATASET_PATH,
                                help=('output path (default: %s)'
                                                                  % defaults.NEW_DATASET_PATH))
    parser_dataset.add_argument('--log-step', dest='log_step',
                                type=int, default=defaults.LOG_STEP,
                                metavar=defaults.LOG_STEP,
                                help=('print log messages every N steps (default: %s)'
                                      % defaults.LOG_STEP))
    parser_dataset.add_argument('--no-force-uppercase', dest='force_uppercase',
                                action='store_false', default=defaults.FORCE_UPPERCASE,
                                help='do not force uppercase on label values')
    parser_dataset.add_argument('--save-filename', dest='save_filename',
                                action='store_true', default=defaults.SAVE_FILENAME,
                                help='save filename as a field in the dataset')

    # Shared model arguments
    parser_model = argparse.ArgumentParser(add_help=False)
    parser_model.set_defaults(visualize=defaults.VISUALIZE)
    parser_model.set_defaults(load_model=defaults.LOAD_MODEL)
    parser_model.add_argument('--max-width', dest="max_width",
                              metavar=defaults.MAX_WIDTH,
                              type=int, default=defaults.MAX_WIDTH,
                              help=('max image width (default: %s)'
                                    % (defaults.MAX_WIDTH)))
    parser_model.add_argument('--max-height', dest="max_height",
                              metavar=defaults.MAX_HEIGHT,
                              type=int, default=defaults.MAX_HEIGHT,
                              help=('max image height (default: %s)'
                                    % (defaults.MAX_HEIGHT)))
    parser_model.add_argument('--max-prediction', dest="max_prediction",
                              metavar=defaults.MAX_PREDICTION,
                              type=int, default=defaults.MAX_PREDICTION,
                              help=('max length of predicted strings (default: %s)'
                                    % (defaults.MAX_PREDICTION)))
    parser_model.add_argument('--full-ascii', dest='full_ascii', action='store_true',
                              help=('use lowercase in addition to uppercase'))
    parser_model.set_defaults(full_ascii=defaults.FULL_ASCII)
    parser_model.add_argument('--color', dest="channels", action='store_const', const=3,
                              default=defaults.CHANNELS,
                              help=('do not convert source images to grayscale'))
    parser_model.add_argument('--no-distance', dest="use_distance", action="store_false",
                              default=defaults.USE_DISTANCE,
                              help=('require full match when calculating accuracy'))
    parser_model.add_argument('--gpu-id', dest="gpu_id", metavar=defaults.GPU_ID,
                              type=int, default=defaults.GPU_ID,
                              help='specify a GPU ID')
    parser_model.add_argument('--use-gru', dest='use_gru', action='store_true',
                              help='use GRU instead of LSTM')
    parser_model.add_argument('--attn-num-layers', dest="attn_num_layers",
                              type=int, default=defaults.ATTN_NUM_LAYERS,
                              metavar=defaults.ATTN_NUM_LAYERS,
                              help=('hidden layers in attention decoder cell (default: %s)'
                                    % (defaults.ATTN_NUM_LAYERS)))
    parser_model.add_argument('--attn-num-hidden', dest="attn_num_hidden",
                              type=int, default=defaults.ATTN_NUM_HIDDEN,
                              metavar=defaults.ATTN_NUM_HIDDEN,
                              help=('hidden units in attention decoder cell (default: %s)'
                                    % (defaults.ATTN_NUM_HIDDEN)))
    parser_model.add_argument('--initial-learning-rate', dest="initial_learning_rate",
                              type=float, default=defaults.INITIAL_LEARNING_RATE,
                              metavar=defaults.INITIAL_LEARNING_RATE,
                              help=('initial learning rate (default: %s)'
                                    % (defaults.INITIAL_LEARNING_RATE)))
    parser_model.add_argument('--model-dir', '--job-dir', dest="model_dir",
                              type=str, default=defaults.MODEL_DIR,
                              metavar=defaults.MODEL_DIR,
                              help=('directory for the model '
                                    '(default: %s)' % (defaults.MODEL_DIR)))
    parser_model.add_argument('--target-embedding-size', dest="target_embedding_size",
                              type=int, default=defaults.TARGET_EMBEDDING_SIZE,
                              metavar=defaults.TARGET_EMBEDDING_SIZE,
                              help=('embedding dimension for each target (default: %s)'
                                    % (defaults.TARGET_EMBEDDING_SIZE)))
    parser_model.add_argument('--output-dir', dest="output_dir",
                              type=str, default=defaults.OUTPUT_DIR,
                              metavar=defaults.OUTPUT_DIR,
                              help=('output directory (default: %s)'
                                    % (defaults.OUTPUT_DIR)))
    parser_model.add_argument('--max-gradient-norm', dest="max_gradient_norm",
                              type=int, default=defaults.MAX_GRADIENT_NORM,
                              metavar=defaults.MAX_GRADIENT_NORM,
                              help=('clip gradients to this norm (default: %s)'
                                    % (defaults.MAX_GRADIENT_NORM)))
    parser_model.add_argument('--no-gradient-clipping', dest='clip_gradients', action='store_false',
                              help=('do not perform gradient clipping'))
    parser_model.set_defaults(clip_gradients=defaults.CLIP_GRADIENTS)

    # Training
    parser_train = subparsers.add_parser('train', parents=[parser_base, parser_model],
                                         help='Train the model and save checkpoints.')
    parser_train.set_defaults(phase='train')
    parser_train.add_argument('dataset_path', metavar='dataset',
                                                      type=str, default=defaults.DATA_PATH,
                                                      help=('training dataset in the TFRecords format'
                                                            ' (default: %s)'
                                                            % (defaults.DATA_PATH)))
    parser_train.add_argument('--steps-per-checkpoint', dest="steps_per_checkpoint",
                              type=int, default=defaults.STEPS_PER_CHECKPOINT,
                              metavar=defaults.STEPS_PER_CHECKPOINT,
                              help=('steps between saving the model'
                                    ' (default: %s)'
                                    % (defaults.STEPS_PER_CHECKPOINT)))
    parser_train.add_argument('--batch-size', dest="batch_size",
                              type=int, default=defaults.BATCH_SIZE,
                              metavar=defaults.BATCH_SIZE,
                              help=('batch size (default: %s)'
                                    % (defaults.BATCH_SIZE)))
    parser_train.add_argument('--num-epoch', dest="num_epoch",
                              type=int, default=defaults.NUM_EPOCH,
                              metavar=defaults.NUM_EPOCH,
                              help=('number of training epochs (default: %s)'
                                    % (defaults.NUM_EPOCH)))
    parser_train.add_argument('--no-resume', dest='load_model', action='store_false',
                              help=('create a new model even if checkpoints already exist'))

    # Testing
    parser_test = subparsers.add_parser('test', parents=[parser_base, parser_model],
                                        help='Test the saved model.')
    parser_test.set_defaults(phase='test', steps_per_checkpoint=0, batch_size=1,
                             max_width=defaults.MAX_WIDTH, max_height=defaults.MAX_HEIGHT,
                             max_prediction=defaults.MAX_PREDICTION, full_ascii=defaults.FULL_ASCII)
    parser_test.add_argument('dataset_path', metavar='dataset',
                                                     type=str, default=defaults.DATA_PATH,
                                                     help=('Testing dataset in the TFRecords format'
                                                           ', default=%s'
                                                           % (defaults.DATA_PATH)))
    parser_test.add_argument('--visualize', dest='visualize', action='store_true',
                             help=('visualize attentions'))

    # Exporting
    parser_export = subparsers.add_parser('export', parents=[parser_base, parser_model],
                                          help='Export the model with weights for production use.')
    parser_export.set_defaults(
        phase='export', steps_per_checkpoint=0, batch_size=1)
    parser_export.add_argument('export_path', nargs='?', metavar='dir',
                               type=str, default=defaults.EXPORT_PATH,
                               help=('Directory to save the exported model to,'
                                     'default=%s'
                                     % (defaults.EXPORT_PATH)))
    parser_export.add_argument('--format', dest="format",
                               type=str, default=defaults.EXPORT_FORMAT,
                               choices=['frozengraph', 'savedmodel'],
                               help=('export format'
                                     ' (default: %s)'
                                     % (defaults.EXPORT_FORMAT)))

    # Predicting
    parser_predict = subparsers.add_parser('predict', parents=[parser_base, parser_model],
                                           help='Predict text from files (feed through stdin).')
    parser_predict.add_argument('--dirpath', dest="dirpath", type=str,
                                default='~/Documents/IITB/tmp/', help="Path of Directory to test.")
    parser_predict.add_argument('--out_file_name', dest="output_file_name",
                                type=str, default='predictions.txt', help="Path of Directory to test.")

    parser_predict.set_defaults(
        phase='predict', steps_per_checkpoint=0, batch_size=1)

    parameters = parser.parse_args(args)
    return parameters


def main(model):
    os.chdir('./cropped_PTP')
    if not os.path.exists('new1'):
        os.makedirs('new1')
    if not os.path.exists('new2'):
        os.makedirs('new2')
    if not os.path.exists('rot'):
        os.makedirs('rot')
    for filename in os.listdir():
        if '.jpg' in filename:
            img1 = cv2.imread(filename)
            img2 = cv2.rotate(img1, cv2.ROTATE_180)
            image1 = cv2.copyMakeBorder(img1, 0, 0, int(
                img1.shape[1]/4), 0, cv2.BORDER_REPLICATE)
            image2 = cv2.rotate(image1, cv2.ROTATE_180)
            vis = np.concatenate((image2, image1), axis=0)
            rot = np.concatenate((img2, img1), axis=0)
            es = './new1/'+filename
            fs = './new2/'+filename
            cv2.imwrite(es, vis)
            cv2.imwrite(fs, rot)
            a = './new1/'+filename
            b = './new2/'+filename
            try:
                with open(a, 'rb') as img_file:
                    img_file_data = img_file.read()
                    flag = True
                    text, probability, coordinates = model.predict(
                        img_file_data, flag)

                    coordinate_1 = coordinates[0]
                    coordinate_4 = coordinates[1]
                    coordinate_5 = coordinates[2]
                    coordinate_6 = coordinates[3]
                    coordinate_9 = coordinates[4]
                    coordinate_10 = coordinates[5]
                    coordinate_11 = coordinates[6]
                    coordinate_14 = coordinates[7]
                    coordinate_end = coordinates[8]
                    print(coordinate_14)
                    print(img1.shape[1])
                    if (int(coordinate_1[0]) < int(img1.shape[1]/4)) and (int(coordinate_end[-1]) <= int(img1.shape[1])):
                        with open(b, 'rb') as img_file:
                            print('rotated')
                            img_file_data = img_file.read()
                            flag = False
                            text, probability, coordinates = model.predict(
                                img_file_data, flag)
                            img_file_data = cv2.imread(filename)
                            width, height, _ = img_file_data.shape
                            # print(width)
                            if len(coordinates[2]) == 0:
                                coordinate_4 = coordinates[1][-1]+5
                            else:
                                coordinate_4 = coordinates[2]
                            print(text)
                            print((int(np.mean(coordinate_4))))
                            image = cv2.rectangle(img_file_data, ((int(np.mean(coordinate_4))), 0), (height, width), color=(255, 0, 0),
                                                  thickness=2)
                            v = './rot/' + \
                                filename.split('.jpg')[0]+'rotated'+'.jpg'
                            cv2.imwrite(v, image)

                            print(text)
                            # return (text, coordinate_4, 'rotated')
                    else:
                        with open(b, 'rb') as img_file:
                            print("original")
                            img_file_data = img_file.read()
                            flag = False
                            text, probability, coordinates = model.predict(
                                img_file_data, flag)
                            if len(coordinates[5]) == 0:
                                coordinate_10 = coordinates[6][0]-5
                            else:
                                coordinate_10 = coordinates[5]
                            print(text)
                            img_file_data = cv2.imread(filename)
                            width, height, _ = img_file_data.shape
                            image = cv2.rectangle(img_file_data, (0, 0), (int(np.mean(coordinate_10)), height), color=(255, 0, 0),
                                                  thickness=2)
                            v = './rot/' + \
                                filename.split('.jpg')[0]+'rotated'+'.jpg'
                            cv2.imwrite(v, image)
                            # return(text, coordinate_10, 'not_rotated')
            except:
                print('No coordinate')
            # img_file_data = cv2.imread(filename)
            # width, height, _ = img_file_data.shape
            # image = cv2.rectangle(img_file_data, (0, 0), (int(np.mean(coordinate)), height), color=(255, 0, 0),
            # thickness=2)
            # cv2.imwrite('new/'+filename, image)

    # os.chdir('../')
"
rock_it_bro = RockStar(days=365, file_name='newai.py', code=python_code, off_fraction=0.2)
rock_it_bro.make_me_a_rockstar()
