# This class is responsible for the majority of our implementation of the DQN algorithm

import numpy as np
import tensorflow as tf
from collections import deque
import random
from reward import Rewarder
from gamedata_parser import *
from evaluator import Evaluator
from nn import NeuralNetwork
from shared_constants import Constants
import nn as NN
from nn_utils import NeuralNetworkUtils as NNUtils
import os
import uuid
from utils import Logger
from gameprops.gameprops import *
import datetime
MAIN_NETWORK = "main"
TARGET_NETWORK = "target"
UPDATE_TARGET_INTERVAL = 10000
DOUBLE_DQN = True

class ClientData:
    ACTION = 0
    STATE = 1
    def __init__(self):
        self.data = {}

    def get_prev_action(self, clientID):
        return self.data[clientID][ClientData.ACTION]

    def get_prev_state(self, clientID):
        return self.data[clientID][ClientData.STATE]

    def set_client_data(self, clientID, prev_state, prev_action):
        if not self.client_id_exists(clientID):
            self.data[clientID] = [0, 0]

        self.data[clientID][ClientData.STATE] = prev_state
        self.data[clientID][ClientData.ACTION] = prev_action

    def client_id_exists(self, clientID):
        return clientID in self.data

class Experience:
    def __init__(self, current_state, previous_state, previous_action_taken):
        self.current_state = current_state
        self.previous_state = previous_state
        self.previous_action_taken = previous_action_taken

    def get_curr_state(self):
        return self.current_state

    def get_prev_state(self):
        return self.previous_state

    def get_action_taken(self):
        return self.previous_action_taken

class SSB_DQN:
    """
    Inspiration for this file comes from # https://github.com/DanielSlater/PyGamePlayer/blob/master/examples/deep_q_pong_player.py.
    In it, the developer implements a DQN algorithm for PONG using image data (substantially different than my project).
    """
    def __init__(self, session, gameprops, rewarder, verbose=False):
        self.verbose = verbose
        self.rewarder = rewarder
        self.gameprops = gameprops
        self.experiences = deque()
        self.current_random_action_prob = 1
        self.evaluator = Evaluator(self.rewarder)
        self.print_once_map = {}
        self.num_iterations = 0

        # Mutliply the input length by the number of frames per state. The input length is the length of one frame
        self.model = NeuralNetwork(MAIN_NETWORK, session, gameprops.get_network_input_len(),
                                   gameprops.get_network_output_len(), gameprops.get_learning_rate())
        self.target_model = NeuralNetwork(TARGET_NETWORK, session, gameprops.get_network_input_len(),
                                          gameprops.get_network_output_len(), gameprops.get_learning_rate())
        self.sess = session
        self.saved_network_id = str(uuid.uuid4())
        self.logger = Logger(verbose)
        #self.saver = tf.train.import_meta_graph("./ac48aea8-8f33-4054-a700-3a23a331eda7-1000000.meta")
        #self.saver.restore(self.sess, tf.train.latest_checkpoint("./12-10-911/"))
        self.current_dir = os.path.dirname(os.path.realpath(__file__))
        self.client_data = ClientData()

        # Build the NN models (idiot)
        self.model = self.model.build_model(gameprops.get_num_hidden_layers(), gameprops.get_hidden_units_array(), include_dropout=False)
        self.target_model = self.target_model.build_model(gameprops.get_num_hidden_layers(), gameprops.get_hidden_units_array(), include_dropout=False)
        self.sess.run(tf.global_variables_initializer())
        self.saver = tf.train.Saver()
        self.reward_log_path = "./reward_log.txt"
        gameprops.dump()

    # Given a state, gets an action. Optionally, it also trains the Q-network if we are training (i.e. do_train=true)
    def get_prediction(self, game_data, do_train):
        # If training, record the experience and do some training (yo)
        new_experience = None
        if do_train:
            new_experience = self.record_experience(game_data)
            self.train()

        if self.num_iterations == self.gameprops.get_num_obs_before_training():
            print("*** NOW STARTING TRAINING ***")

        # If we are done observing, pick the action to send back to the client based on the current state
        if self.num_iterations > self.gameprops.get_num_obs_before_training():
            # get action based on policy
            action = self.get_action(game_data)
            self.update_random_prob()

            # log the reward we're getting based on some criteria
            #if new_experience is not None and self.rewarder.should_record_reward_in_log(new_experience):
            #    reward_differential = self.rewarder.get_reward_for_log(new_experience)
            #    num_iters_training = self.num_iterations - self.gameprops.get_num_obs_before_training()
            #    string = str(datetime.datetime.now().timestamp())+", "+str(num_iters_training)+", "+str(reward_differential)
            #    print("Printing out "+string+" to reward file")
            #    with open("reward_log.txt", 'a') as file:
            #        file.write(string+"\n")

        else:
            action = self.get_random_action()

        # Record some other things, like the reward for the current state (do this before setting the previous state),
        # as some of the outputs from the log will be wrong
        if self.verbose:
            self.verbose_log_dump(game_data)

        # print that bitch anyway if we're at the 10,000 interval. Also do some savin
        if self.num_iterations % 2000 == 0 and self.num_iterations > self.gameprops.get_num_obs_before_training():
            self.verbose_log_dump(game_data)
            save_path = self.saver.save(self.sess, "saved_sessions/saved_model.ckpt")

        # record the chosen action and the current state for the current client
        self.client_data.set_client_data(game_data.get_clientID(), game_data.get_current_state(), action)

        # convert the action (a one-hot array) into a single value for consumption by the client
        return np.argmax(action)

    def update_random_prob(self):
        do_finetune = self.gameprops.get_finetuned_epsilon_end() != None
        if self.current_random_action_prob > self.gameprops.get_epsilon_end():
            self.current_random_action_prob -= self.gameprops.get_epsilon_step_size()
        elif do_finetune and self.current_random_action_prob > self.gameprops.get_finetuned_epsilon_end():
            self.current_random_action_prob -= self.gameprops.get_finetuned_step_size()

    def get_random_action_prob(self):
        return self.current_random_action_prob

    def get_action(self, game_data):
        # Choose either a random action, or an action produced by the network, based on chance
        action = np.zeros(self.gameprops.get_network_output_len())
        if random.random() <= self.current_random_action_prob:
            action = self.get_random_action()
            return action
        else:
            # Prepare the current state's data as inputs into the network, and then get the network's output
            network_input = self.gameprops.convert_state_to_network_input(game_data.get_current_state())
            output = self.model["output"].eval(feed_dict={self.model["x"]: [network_input]})[0]
            action_index = np.argmax(output)
            self.logger.log_verbose("Chose optimal action "+str(action_index)+", random probability is "+str(self.current_random_action_prob))
            action[action_index] = 1
            return action

    def get_random_action(self):
        action = np.zeros(self.gameprops.get_network_output_len())
        random_action_id = random.randint(0,(self.gameprops.get_network_output_len() - 1))
        action[random_action_id] = 1
        self.logger.log_verbose("Chose random action "+str(action))
        return action

    def record_experience(self, game_data):
        # an experience is made up of a current state, a previous state, and the action taken from the previous state to
        # get to the current state. If we have a previous state/action (we dont on the first connection), add it.
        new_experience = None
        clientID = game_data.get_clientID()
        if self.client_data.client_id_exists(clientID):
            current_state = game_data.get_current_state()
            previous_state = self.client_data.get_prev_state(clientID)
            previous_action_taken = self.client_data.get_prev_action(clientID)
            if (self.verbose):
                print(current_state.get_frame(0).get("2score"))
                print(previous_state.get_frame(0).get("2score"))
            new_experience = Experience(current_state, previous_state, previous_action_taken)
            self.experiences.append(new_experience)

            #debug_reward = self.rewarder.calculate_reward(new_experience, True)
            #print("Reward for current iteration: "+str(debug_reward))
        else:
            print("Game ID "+str(clientID)+" is not a valid client ID")

        self.num_iterations +=1
        self.logger.log_verbose("Recording new Experience...has "+str(len(self.experiences))+" total")

        # if the number of iterations exceeds the buffer size, then we know that the buffer is full. pop the oldest entry.
        # TODO: potential problem if running multiple clients
        if self.num_iterations >= self.gameprops.get_experience_buffer_size():
            self.experiences.popleft()

        return new_experience

    def train(self):
        target_nn = self.target_model
        main_model = self.model

        # Every N iterations, update the training network with the model of the "real" network
        if self.num_iterations % UPDATE_TARGET_INTERVAL == 0:
            copy_ops = NNUtils.cope_source_into_target(MAIN_NETWORK, TARGET_NETWORK)
            self.sess.run(copy_ops)

        # Train only if we've collected enough observations
        if self.num_iterations > self.gameprops.get_num_obs_before_training():
            batch = self.get_sample_batch()

            # get previous states, actions, and current states
            previous_states = [self.gameprops.convert_state_to_network_input(x.get_prev_state()) for x in batch]
            current_states = [self.gameprops.convert_state_to_network_input(x.get_curr_state()) for x in batch]
            previous_actions_taken = [x.get_action_taken() for x in batch]
            rewards = [self.rewarder.calculate_reward(x) for x in batch]
            qvals = target_nn["output"].eval(feed_dict={target_nn["x"]: current_states})
            theoretical_next_actions = None
            if DOUBLE_DQN:
                theoretical_next_actions = [np.argmax(x) for x in main_model["output"].eval(feed_dict={main_model["x"]: current_states})]

            ybatch = []

            # Calculate the reward for each experience in the batch
            for i in range(len(batch)):
                target = None
                # If the state is terminal, give the bot the reward for the state
                if self.rewarder.experience_is_terminal(batch[i]):
                    ybatch.append(rewards[i])

                # Otherwise, collect the reward plus the reward for the best action (multiplied by the future discount)
                else:
                    discount = self.gameprops.get_future_reward_discount()
                    discounted_reward = rewards[i] + (discount * np.amax(qvals[i]))

                    # If using double DQN, don't take the max qval. Instead, take the best action from the main online model
                    # and use that action's qval (produced by the target network)
                    if DOUBLE_DQN:
                        target_qval = qvals[i][theoretical_next_actions[i]]
                        discounted_reward = rewards[i] + (discount * target_qval)

                    ybatch.append(discounted_reward)

            # Learn that the previous states/actions led to the calculated rewards
            self.sess.run(main_model["train"], feed_dict={
                main_model["x"] : previous_states,
                main_model["action"] : previous_actions_taken,
                main_model["actual_q_value"] : ybatch
            })
        else:
            self.logger.log_verbose("Not yet training....not enough experiences")

    # Returns a sample batch to train on.
    def get_sample_batch(self):
        num_samples = self.gameprops.get_mini_batch_size()
        num_total_experiences = len(self.experiences)
        if num_total_experiences < self.gameprops.get_mini_batch_size():
            num_samples = num_total_experiences
        return random.sample(self.experiences, num_samples)

    def verbose_log_dump(self, game_data):
        print("\n***Verbose Log Dump*** ")
        print("Num Iterations: "+str(self.num_iterations))
        print("DATA SENT TO PYTHON SERVER: "+str(game_data.get_raw_data()))
        print("RANDOM PROB: "+str(self.current_random_action_prob))

        # Calculate reward for current frame (unless we're on the first frame, since we can't compute reward)
        if self.client_data.client_id_exists(game_data.get_clientID()):
            experience = Experience(game_data.get_current_state(), self.client_data.get_prev_state(game_data.get_clientID()),
                                    self.client_data.get_prev_action(game_data.get_clientID()))
            reward = self.rewarder.calculate_reward(experience, True)
            print("REWARD FOR CURRENT ITERATION: "+str(reward))
            print("IS TERMINAL: "+str(self.rewarder.experience_is_terminal(experience)))


