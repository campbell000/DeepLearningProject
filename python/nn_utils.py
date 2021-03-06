import numpy as np
import tensorflow as tf
import random
import os
import uuid

class NeuralNetworkUtils:
    # This method returns operations to copy the weights/variables from the src network to the destination network.
    @staticmethod
    def cope_source_into_target(src_name, dest_name):
        op_holder = []

        src_vars = tf.get_collection(
            tf.GraphKeys.TRAINABLE_VARIABLES, scope=src_name)
        dest_vars = tf.get_collection(
            tf.GraphKeys.TRAINABLE_VARIABLES, scope=dest_name)

        for src_var, dest_var in zip(src_vars, dest_vars):
            op_holder.append(dest_var.assign(src_var.value()))

        return op_holder

    @staticmethod
    def get_one_hot(value, num_possible_classes):
        return np.eye(num_possible_classes)[value]

    @staticmethod
    def get_random_action(number_of_actions):
        return random.randint(0,(number_of_actions - 1))

    @staticmethod
    def flatten_image(arr):
        for aidx, a in enumerate(arr):
            for bidx, b in enumerate(a):
                a[bidx] = b[0]

    # normalizes between -1 and 1
    @staticmethod
    def normalize(x, min, max):
        if min >= max:
            raise Exception("CANT DO THIS")
        return 2 * ((x - min) / (max - min)) - 1


