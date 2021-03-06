from gameprops.gameprops import *
from shared_constants import Constants
from shared_constants import SharedConstants
from gamedata_parser import *
import numpy as np
import imageio
from PIL import Image
from io import BytesIO
import base64

# A subclass of the GameProps specific to Pong.
class PongScreenshotGameProps(GameProps):

    def __init__(self):
        # HARDCODED RESULTS OF SCREENSHOT CROPPING
        self.LEFT = 27
        self.TOP = 31
        self.RIGHT = 20
        self.BOTTOM = 14
        IMAGE_WIDTH = (320 - self.LEFT) - self.RIGHT
        IMAGE_HEIGHT = (240 - self.TOP) - self.BOTTOM

        shared_props = SharedConstants()
        num_frames_per_state = shared_props.get_prop_val('pong_screenshot', 'num_frames_per_state')
        self.pong_input_length = (IMAGE_HEIGHT * num_frames_per_state, IMAGE_WIDTH, 3)
        super(PongScreenshotGameProps, self).__init__(self.pong_input_length, 3) # 3 actions: up, down, and stand still
        self.cnn_params = [
            [32, 8, 4],
            [64, 4, 2],
            [64, 3, 1]
        ]
        self.do_grayscale = True # don't need color
        self.hidden_units_arr = [512, 256]
        self.experience_buffer_size = 50000
        self.future_reward_discount = 0.95
        self.mini_batch_size = 16
        self.num_obs_before_training = 16

        # Slowly make agent less random
        self.anneal_epsilon = True
        self.num_steps_epislon_decay = 500000
        self.epsilon_end =  0.05
        self.epsilon_step_size = (1 - self.epsilon_end) / self.num_steps_epislon_decay
        self.img_scaling_factor = 3
        self.preprocessed_input_length = (int(IMAGE_HEIGHT/self.img_scaling_factor) * num_frames_per_state,
                                          int(IMAGE_WIDTH/self.img_scaling_factor), 1)

    def is_conv(self):
        return True

    def get_conv_params(self):
        return self.cnn_params

    def convert_state_to_network_input(self, state, reverse=False):
        input = []
        for i in range(state.get_num_frames()):
            data = state.get_frame(i)
            try :
                cleaned_image_data = data.get("image").strip('\n').strip('\r').replace(' ', '+')
                image = Image.open(BytesIO(base64.b64decode(cleaned_image_data + "==="))) # https://gist.github.com/perrygeo/ee7c65bb1541ff6ac770
            except:
                print(data.get("image"))
                raise Exception("AHHHH")
            w, h = image.size
            cropped = image.crop((self.LEFT, self.TOP, w - self.RIGHT, h - self.BOTTOM))
            image_array = np.asarray(cropped)
            if len(input) == 0:
                input = image_array
            else:
                input = np.vstack((input, image_array))
        return input