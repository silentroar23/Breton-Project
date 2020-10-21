#%% imports
import os
import time
import progressbar
from util_vel_pred import *
# from energy_opt_v1 import *
from energy_opt_v2 import *
from energy_opt_v3 import *
import pickle
from fuzzy_w_modify import *
import math
import pdb
# 1.去掉车速轨迹优化 2.加v2，3.放宽里程的限制。(挡位，轮边扭矩，电机效率，车速，权重，权重变化，电机扭矩。能耗)4.
#%% utility functions
def find(list, value):
	return [i for i, x in enumerate(list) if x == value]

#%% model parameters
n_steps_in = 15
n_steps_out = 10
n_features = 2
batch_size = 64

enc_input_size = 1
dec_input_size = 1
enc_hidden_size = 32
dec_hidden_size = 32
enc_num_layers = 2
dec_num_layers = 2
dec_output_size = 1

BIDIRECTIONAL = False
rnn = nn.LSTM

device = 'cpu'
		
enc = Encoder(batch_size, enc_input_size, enc_hidden_size, enc_num_layers, rnn=rnn)
attn = Attention(enc_hidden_size, dec_hidden_size)
dec = Decoder(n_steps_out, dec_input_size, enc_hidden_size, dec_hidden_size, dec_output_size, dec_num_layers, attention=attn, rnn=rnn)
model = Seq2Seq(enc, dec, require_attention=False).to(device)
# model.load_state_dict(torch.load('/Users/tujiayu/Dev/BretonProject/Velocity Prediction/models/0427seq2seqWithAttention-layers2-units32-wd0.001-lr1e-5-2e-4.pth'))
# model.load_state_dict(torch.load('models/0427seq2seqNoAttention-layers2-units32-wd0.001-lr1e-5-3e-4.pth'))
model.load_state_dict(torch.load('models/0705seq2seqNoAttention-no-acc-layers2-units32-wd0.001-lr12e-5-2e-4-minmax.pth'))

#%% extract valid sequences from files
vel_CAN_cycle = 0.2  # unit: s
vel_count_per_second = int(1 / vel_CAN_cycle)
dataFolder = os.path.join('Data', 'BretonDataTest')
velocity_files = os.listdir(dataFolder)
velocity_files.sort()

#%%
res = []
ori = []
for file in velocity_files:
	# file = '0618_1.csv'
	fileName = os.path.join(dataFolder, file)
	df = pd.read_csv(fileName, header=None, sep='\s+', names=['vel', 'acc', 'brake', 'gear', 'gearFlag'],
		dtype={'vel': np.float32, 'acc': np.float32, 'brake': np.float32, 'gear': np.float32, 'gearFlag': np.float32})
	velocity = df['vel'].values
	gear = df['gear'].values
	gearFlag = df['gearFlag'].values
	acc = df['acc'].values
	brake = df['brake'].values

	assert velocity.size == gear.size == acc.size == brake.size

	valid_indexes = extractValidSeq(gearFlag)
	sorted_indexes = sorted(valid_indexes, key=lambda x: x.size, reverse=True)

	for cnt, idx in enumerate(sorted_indexes):

		if cnt >= 20:
			break
		
		if idx.size >= 20 * 60 * 5:  # 20 mins
			V = velocity[idx]
			A = acc[idx]
			B = brake[idx]
			G = gear[idx]

			v = np.array([V[i:i + vel_count_per_second].mean() for i in range(0, V.size, vel_count_per_second) if i + vel_count_per_second <= V.size])

			# if an average is used, there may be cases where both the accelerator and brake are greater than 0
			a = np.array([A[i] for i in range(0, A.size, vel_count_per_second) if i + vel_count_per_second <= A.size])
			b = np.array([B[i] for i in range(0, B.size, vel_count_per_second) if i + vel_count_per_second <= B.size])
			g = np.array([G[i] for i in range(0, G.size, vel_count_per_second) if i + vel_count_per_second <= G.size])

			data = np.vstack((v, a)) 
			data = moving_average(data)  # (n_features, )
			v = moving_average(v)

			mode = 'min-max'
			assert data[0].shape == g.shape == b.shape == a.shape

			# data, a, b, g should not be changed, use copy of them if want to access a slice of them

			# %%
			deta_torque_wheel = 1500
			count = 0
			W = 0.5
			w1 = 1
			opt_results_v2 = {}


			################ 存储标志位 ################
			opt_results_v2['flag'] = []

			################ 存储纯优化的数据 ################
			opt_results_v2['flag_motor_speed_opt'] = []
			opt_results_v2['flag_torque_opt'] = []
			opt_results_v2['vel_opt'] = [] 
			opt_results_v2['torque_opt'] = []  
			opt_results_v2['gear_opt'] = []
			opt_results_v2['motor_eff_opt'] = []
			opt_results_v2['energy_opt'] = []
			opt_results_v2['torque_wheel_opt'] = []
			opt_results_v2['motor_speed_opt'] = []

			################ 存储原始数据 ################
			opt_results_v2['flag_motor_speed_dmd'] = []
			opt_results_v2['flag_torque_dmd'] = []
			opt_results_v2['vel_dmd'] = []
			opt_results_v2['torque_dmd'] = []
			opt_results_v2['gear_dmd'] = []
			opt_results_v2['motor_eff_dmd'] = []

			opt_results_v2['torque_wheel_dmd'] = []
			opt_results_v2['motor_speed_dmd'] = []

			################ 存储实际执行的数据（兼顾驾驶意图的） ################
			opt_results_v2['flag_motor_speed_ctl'] = []
			opt_results_v2['flag_torque_ctl'] = []
			opt_results_v2['vel_ctl'] = []
			opt_results_v2['torque_ctl'] = []
			opt_results_v2['gear_ctl'] = []
			opt_results_v2['motor_eff_ctl'] = []
			opt_results_v2['energy_ctl'] = []
			opt_results_v2['torque_wheel_ctl'] = []
			opt_results_v2['motor_speed_ctl'] = []

			# ################ 存储权重及权重变化率 ################
			opt_results_v2['w1'] = []
			opt_results_v2['W'] = []
			distance_ctl = []
			distance_dmd = []
			################ 一些并不知道为什么要存的东西 ################
			opt_results_v2['mean_vel_past'] = []
			opt_results_v2['mean_vel_pred'] = []
			opt_results_v2['mean_vel_real'] = []
			opt_results_v2['mean_vel_opt'] = []
			opt_results_v2['invalid_indexes'] = []
			opt_results_v2['vel_real'] = []
			opt_results_v2['vel_pred'] = []
			opt_results_v2['vel_min'] = []
			opt_results_v2['vel_max'] = []
			opt_results_v2['if_opt'] = []
			opt_results_v2['abnormal_vel'] = []
			opt_results_v2['vel_mean'] = []
			opt_results_v2['Tm_wheel_diff_ctl'] = []
			opt_results_v2['drive_mode'] = []

			###########################  开始运算  ########################### 
			vel_only = True
			if vel_only == True:
				data = v

			#%% segment optimization with dp
			# backward simulation does not need to determine the vehicle state (drive, brake, slide, etc.)
			# for i in progressbar.progressbar(range(n_steps_in, 100)):#data.shape[1] - n_steps_out)):
			plt.style.use('ggplot')

			for i in progressbar.progressbar(range(n_steps_in, v.size - n_steps_out)):
			# for i in progressbar.progressbar(range(n_steps_in, 500)):
				if i == n_steps_in:
					# Calculate original velocity, torque, motor_eff, energy
					vel_current = v[i - 1]										# vel_current km/h
					vel_next = v[i]												# vel_next km/h
					gear_former = gears_in_use[int(g[i - 1]) - 1]
					gear_next = gears_in_use[int(g[i - 1]) - 1]
					
					_, torque, _ = motor_torque_calc(vel_current / 3.6 ,vel_next / 3.6, gear_next)	

					if vel_only == True:
						vel_seq = data[i - n_steps_in:i + n_steps_out].copy()  # vel_seq: km/h
					else:
						vel_seq = data[0, i - n_steps_in:i + n_steps_out].copy()
					
					data_history = data[i - n_steps_in:i].copy()  # need to update every iteration; data_history:km/h
				else:
					vel_current = vel_next
					vel_next = v[i]
					gear_next, _, _ = modify_gear(vel_current/3.6, vel_next/3.6, gear_former, gears_in_use)  # last step 
					gear_former = gear_ctl
					
					_, torque, _ = motor_torque_calc(vel_current / 3.6 ,vel_next / 3.6, gear_next)	

					if vel_only == True:
						vel_seq = data[i - n_steps_in:i + n_steps_out].copy()
						vel_seq[n_steps_in-1] = vel_current
					else:
						vel_seq = data[0, i - n_steps_in:i + n_steps_out].copy()
						vel_seq[0, n_steps_in-1] = vel_current

				# optimization module is activated only when the car is in drive mode
				if torque >= 0:
					# the past {n_steps_in} seconds of velocity should all > 0
					if np.isclose(np.isclose(vel_seq, np.zeros(n_steps_in + n_steps_out)).astype('float32').sum(), 0):
						# i is current step
						# if vel_only == True:
						# 	# data_history = data[i - n_steps_in:i].copy()
						# 	# data_history[-1] = vel_current  # update velocity
						# 	vel_history = data[i - n_steps_in:i].copy()
						# else:
						# 	# data_history = data[:, i - n_steps_in:i].copy()  
						# 	# data_history[0, -1] = vel_current
						# 	vel_history = data[:, i - n_steps_in:i].copy()
						# vel_history[-1] = vel_current

						if mode == 'min-max':
							if vel_only == True:
								# print(data_history)
								vel_pred = predict(data_history / 85, model) * 85		
								# print(vel_pred)
							else:
								vel_pred = predict(data_history / 85, model) * 85
						elif mode == 'std':
							if vel_only == True:
								data_history[0] = (data_history[0] - v_mean) / v_std
								data_history[1] = (data_history[1] - a_mean) / a_std
								vel_pred = predict(data_history.transpose(), model) * v_std + v_mean
							else:
								data_history = (data_history - v_mean) / v_std

						vel_pred = vel_pred.detach().numpy()	# vel_pred: km/h
						if vel_only == True:
							vel_real = data[i:i + n_steps_out].copy()
						else:
							vel_real = data[0, i:i + n_steps_out].copy()

						
						if np.count_nonzero(vel_pred <= 0) > 0:

							flag = -1 
							count = 0
							vel_ctl = vel_next
							vel_optimize = -1
							vel_dmd = vel_next

							gear_dmd = gear_next
							gear_ctl, _  = choose_gear(vel_current/3.6, vel_ctl/3.6, gear_former)
							gear_optimize = -1
						
							energy_ctl, torque_seq_ctl, motor_eff_seq_ctl, flag_motor_speed_ctl, flag_torque_ctl, motor_speed_ctl = energy_and_motor_eff_calc(np.array([vel_current, vel_ctl])/3.6, np.array([gear_ctl]), per_meter=False)
							_, torque_seq_dmd, motor_eff_seq_dmd, flag_motor_speed_dmd, flag_torque_dmd, motor_speed_dmd = energy_and_motor_eff_calc(np.array([vel_current, vel_dmd])/3.6, np.array([gear_dmd]), per_meter=False)
							
							torque_wheel_ctl = torque_seq_ctl[0] * gear_ctl * i0 * eff_diff * eff_cpling if torque_seq_ctl[0] > 0 else torque_seq_ctl[0] * gear_ctl * i0 / (eff_diff * eff_cpling * Reg_rate)
							torque_wheel_dmd = torque_seq_dmd[0] * gear_dmd * i0 * eff_diff * eff_cpling if torque_seq_dmd[0] > 0 else torque_seq_dmd[0] * gear_dmd * i0 / (eff_diff * eff_cpling * Reg_rate)

							if torque_wheel_ctl - torque_wheel_dmd > deta_torque_wheel:
								torque_wheel_ctl = torque_wheel_dmd + deta_torque_wheel
								vel_ctl = vel_calc_with_torque_wheel(torque_wheel_ctl, vel_current/3.6) * 3.6
								gear_ctl, _ = choose_gear(vel_current/3.6, vel_ctl/3.6, gear_former)
								energy_ctl, torque_seq_ctl, motor_eff_seq_ctl, flag_motor_speed_ctl, flag_torque_ctl, motor_speed_ctl = energy_and_motor_eff_calc(np.array([vel_current, vel_ctl])/3.6, np.array([gear_ctl]), per_meter=False)
							elif torque_wheel_dmd - torque_wheel_ctl > deta_torque_wheel:
								torque_wheel_ctl = torque_wheel_dmd - deta_torque_wheel	
								vel_ctl = vel_calc_with_torque_wheel(torque_wheel_ctl, vel_current/3.6) * 3.6
								gear_ctl, _ = choose_gear(vel_current/3.6, vel_ctl/3.6, gear_former)
								energy_ctl, torque_seq_ctl, motor_eff_seq_ctl, flag_motor_speed_ctl, flag_torque_ctl, motor_speed_ctl = energy_and_motor_eff_calc(np.array([vel_current, vel_ctl])/3.6, np.array([gear_ctl]), per_meter=False)
			
							#### 速度更新 ####
							vel_next = vel_ctl
							data_history = np.hstack([data_history[1:], [vel_next]])

							vel_mean = distance_calc(vel_current / 3.6, vel_ctl / 3.6)
							print(f'step {i - 15}: Invalid velocity prediction')
						else:
							(vel_opt, vel_min, vel_max, Tm_opt, gear_opt, motor_eff_opt, flag) = energy_opt_v2(vel_current / 3.6, vel_pred.squeeze(0) / 3.6, gear_former)

							# 转矩融合模块
							if flag == 1:
								count = count + 1
								vel_ctl = vel_opt[1]
								vel_optimize = vel_opt[1]
								vel_dmd = vel_next

								gear_dmd, flag_gear = choose_gear(vel_current/3.6, vel_dmd/3.6, gear_former)
								gear_optimize = gear_opt[0]
								gear_ctl = gear_opt[0]

								_, torque_seq_dmd, motor_eff_seq_dmd, flag_motor_speed_dmd, flag_torque_dmd, motor_speed_dmd = energy_and_motor_eff_calc(np.array([vel_current/3.6, vel_next/3.6]), np.array([gear_dmd]), per_meter=False)
								energy_ctl, torque_seq_ctl, motor_eff_seq_ctl, flag_motor_speed_ctl, flag_torque_ctl, motor_speed_ctl = energy_and_motor_eff_calc(np.array([vel_current, vel_ctl])/3.6, np.array([gear_ctl]), per_meter=False)
								energy_opt, torque_seq_opt, motor_eff_seq_opt, flag_motor_speed_opt, flag_torque_opt, motor_speed_opt = energy_and_motor_eff_calc(np.array([vel_current, vel_optimize])/3.6, np.array([gear_opt[0]]), per_meter=False)
								torque_opt = torque_seq_opt[0]
								motor_eff_opt = motor_eff_seq_opt[0]

								torque_wheel_ctl = torque_seq_ctl[0] * gear_opt[0] * i0 * eff_diff * eff_cpling if torque_seq_ctl[0] > 0 else torque_seq_ctl[0] * gear_opt[0] * i0 / (eff_diff * eff_cpling * Reg_rate)
								torque_wheel_opt = torque_seq_opt[0] * gear_opt[0] * i0 * eff_diff * eff_cpling if torque_seq_opt[0] > 0 else torque_seq_opt[0] * gear_opt[0] * i0 / (eff_diff * eff_cpling * Reg_rate)
								torque_wheel_dmd = torque_seq_dmd[0] * gear_dmd * i0 * eff_diff * eff_cpling if torque_seq_dmd[0] > 0 else torque_seq_dmd[0] * gear_dmd[0] * i0 / (eff_diff * eff_cpling * Reg_rate)

								vel_aver_ctl = (vel_ctl / 3.6 + vel_current / 3.6) / 2 
								vel_aver_dmd = (vel_dmd / 3.6 + vel_current / 3.6) / 2
								distance_ctl.append(vel_aver_ctl)
								distance_dmd.append(vel_aver_dmd)
								if count == 10:
									distance_delta = (sum(distance_ctl) - sum(distance_dmd)) / sum(distance_dmd)
									w1 = w_modify(distance_delta)
									W = min(1, W * w1)
			
									torque_wheel_ctl = W * torque_wheel_ctl + (1 - W) * torque_wheel_dmd
									count = 0
									distance_ctl = []
									distance_dmd = []
								if torque_wheel_ctl - torque_wheel_dmd > deta_torque_wheel:
									torque_wheel_ctl = torque_wheel_dmd + deta_torque_wheel
									vel_ctl = vel_calc_with_torque_wheel(torque_wheel_ctl, vel_current/3.6) * 3.6
									gear_ctl, _ = choose_gear(vel_current/3.6, vel_ctl/3.6, gear_former)
									energy_ctl, torque_seq_ctl, motor_eff_seq_ctl, flag_motor_speed_ctl, flag_torque_ctl, motor_speed_ctl = energy_and_motor_eff_calc(np.array([vel_current, vel_ctl])/3.6, np.array([gear_ctl]), per_meter=False)
								elif torque_wheel_dmd - torque_wheel_ctl > deta_torque_wheel:
									torque_wheel_ctl = torque_wheel_dmd - deta_torque_wheel	
									vel_ctl = vel_calc_with_torque_wheel(torque_wheel_ctl, vel_current/3.6) * 3.6
									gear_ctl, _ = choose_gear(vel_current/3.6, vel_ctl/3.6, gear_former)
									energy_ctl, torque_seq_ctl, motor_eff_seq_ctl, flag_motor_speed_ctl, flag_torque_ctl, motor_speed_ctl = energy_and_motor_eff_calc(np.array([vel_current, vel_ctl])/3.6, np.array([gear_ctl]), per_meter=False)


								#### 速度更新 ####
								vel_next = vel_ctl
								data_history = np.hstack([data_history[1:], [vel_next]])
								
								vel_mean = distance_calc(vel_current/3.6, vel_ctl/3.6)



							elif flag == 0:
								print(f'step {i - 15}: Invalid dp calculation')
								count = 0
								# torque_ctl = torque_ori
								vel_ctl = vel_next
								vel_optimize = -1
								vel_dmd = vel_next


								gear_dmd = gear_next
								gear_ctl, _ = choose_gear(vel_current/3.6, vel_ctl/3.6, gear_former)
								gear_optimize = -1

								energy_ctl, torque_seq_ctl, motor_eff_seq_ctl, flag_motor_speed_ctl, flag_torque_ctl, motor_speed_ctl = energy_and_motor_eff_calc(np.array([vel_current, vel_ctl])/3.6, np.array([gear_ctl]), per_meter=False)
								_, torque_seq_dmd, motor_eff_seq_dmd, flag_motor_speed_dmd, flag_torque_dmd, motor_speed_dmd = energy_and_motor_eff_calc(np.array([vel_current, vel_dmd])/3.6, np.array([gear_dmd]), per_meter=False)
								
								torque_wheel_ctl = torque_seq_ctl[0] * gear_ctl * i0 * eff_diff * eff_cpling if torque_seq_ctl[0] > 0 else torque_seq_ctl[0] * gear_ctl * i0 / (eff_diff * eff_cpling * Reg_rate)
								torque_wheel_dmd = torque_seq_dmd[0] * gear_dmd * i0 * eff_diff * eff_cpling if torque_seq_dmd[0] > 0 else torque_seq_dmd[0] * gear_dmd * i0 / (eff_diff * eff_cpling * Reg_rate)
								
								if torque_wheel_ctl - torque_wheel_dmd > deta_torque_wheel:
									torque_wheel_ctl = torque_wheel_dmd + deta_torque_wheel
									vel_ctl = vel_calc_with_torque_wheel(torque_wheel_ctl, vel_current/3.6) * 3.6
									gear_ctl, _ = choose_gear(vel_current/3.6, vel_ctl/3.6, gear_former)
									energy_ctl, torque_seq_ctl, motor_eff_seq_ctl, flag_motor_speed_ctl, flag_torque_ctl, motor_speed_ctl = energy_and_motor_eff_calc(np.array([vel_current, vel_ctl])/3.6, np.array([gear_ctl]), per_meter=False)
								elif torque_wheel_dmd - torque_wheel_ctl > deta_torque_wheel:
									torque_wheel_ctl = torque_wheel_dmd - deta_torque_wheel	
									vel_ctl = vel_calc_with_torque_wheel(torque_wheel_ctl, vel_current/3.6) * 3.6
									gear_ctl, _ = choose_gear(vel_current/3.6, vel_ctl/3.6, gear_former)
									energy_ctl, torque_seq_ctl, motor_eff_seq_ctl, flag_motor_speed_ctl, flag_torque_ctl, motor_speed_ctl = energy_and_motor_eff_calc(np.array([vel_current, vel_ctl])/3.6, np.array([gear_ctl]), per_meter=False)

								### 速度更新
								vel_next = vel_ctl
								data_history = np.hstack([data_history[1:], [vel_next]])

								vel_mean = distance_calc(vel_current/3.6, vel_ctl/3.6)
								
					# the past {n_steps_in} seconds of velocity exists 0
					else:
						print(f'step {i - 15}: the past {n_steps_in} seconds of velocity exists 0')
						flag = 2
						count = 0
						vel_ctl = vel_next
						vel_optimize = -1
						vel_dmd = vel_next

						gear_dmd = gear_next
						gear_ctl, _ = choose_gear(vel_current/3.6, vel_ctl/3.6, gear_former)
						gear_optimize = -1

						energy_ctl, torque_seq_ctl, motor_eff_seq_ctl, flag_motor_speed_ctl, flag_torque_ctl, motor_speed_ctl = energy_and_motor_eff_calc(np.array([vel_current, vel_ctl])/3.6, np.array([gear_ctl]), per_meter=False)
						_, torque_seq_dmd, motor_eff_seq_dmd, flag_motor_speed_dmd, flag_torque_dmd, motor_speed_dmd = energy_and_motor_eff_calc(np.array([vel_current, vel_dmd])/3.6, np.array([gear_dmd]), per_meter=False)

						torque_wheel_ctl = torque_seq_ctl[0] * gear_ctl * i0 * eff_diff * eff_cpling if torque_seq_ctl[0] > 0 else torque_seq_ctl[0] * gear_ctl * i0 / (eff_diff * eff_cpling * Reg_rate)
						torque_wheel_dmd = torque_seq_dmd[0] * gear_dmd * i0 * eff_diff * eff_cpling if torque_seq_dmd[0] > 0 else torque_seq_dmd[0] * gear_dmd * i0 / (eff_diff * eff_cpling * Reg_rate)

						if torque_wheel_ctl - torque_wheel_dmd > deta_torque_wheel:
							torque_wheel_ctl = torque_wheel_dmd + deta_torque_wheel
							vel_ctl = vel_calc_with_torque_wheel(torque_wheel_ctl, vel_current/3.6) * 3.6
							gear_ctl, _ = choose_gear(vel_current/3.6, vel_ctl/3.6, gear_former)
							energy_ctl, torque_seq_ctl, motor_eff_seq_ctl, flag_motor_speed_ctl, flag_torque_ctl, motor_speed_ctl = energy_and_motor_eff_calc(np.array([vel_current, vel_ctl])/3.6, np.array([gear_ctl]), per_meter=False)
						elif torque_wheel_dmd - torque_wheel_ctl > deta_torque_wheel:
							torque_wheel_ctl = torque_wheel_dmd - deta_torque_wheel	
							vel_ctl = vel_calc_with_torque_wheel(torque_wheel_ctl, vel_current/3.6) * 3.6
							gear_ctl, _ = choose_gear(vel_current/3.6, vel_ctl/3.6, gear_former)
							energy_ctl, torque_seq_ctl, motor_eff_seq_ctl, flag_motor_speed_ctl, flag_torque_ctl, motor_speed_ctl = energy_and_motor_eff_calc(np.array([vel_current, vel_ctl])/3.6, np.array([gear_ctl]), per_meter=False)

						#### 速度更新 ####
						vel_next = vel_ctl
						data_history = np.hstack([data_history[1:], [vel_next]])
						
						vel_mean = distance_calc(vel_current/3.6, vel_ctl/3.6)


				else:
					print(f'step {i - 15}: does not enter optimization module\n')
					# update data_history
					flag = 3
					count = 0
					vel_ctl = vel_next
					vel_optimize = -1
					vel_dmd = vel_next

					gear_dmd = gear_next
					gear_ctl, _ = choose_gear(vel_current/3.6, vel_ctl/3.6, gear_former)
					gear_optimize = -1

					energy_ctl, torque_seq_ctl, motor_eff_seq_ctl, flag_motor_speed_ctl, flag_torque_ctl, motor_speed_ctl = energy_and_motor_eff_calc(np.array([vel_current, vel_ctl])/3.6, np.array([gear_ctl]), per_meter=False)
					_, torque_seq_dmd, motor_eff_seq_dmd, flag_motor_speed_dmd, flag_torque_dmd, motor_speed_dmd = energy_and_motor_eff_calc(np.array([vel_current, vel_dmd])/3.6, np.array([gear_dmd]), per_meter=False)
					
					torque_wheel_ctl = torque_seq_ctl[0] * gear_ctl * i0 * eff_diff * eff_cpling if torque_seq_ctl[0] > 0 else torque_seq_ctl[0] * gear_ctl * i0 / (eff_diff * eff_cpling * Reg_rate)
					
					vel_next = vel_ctl
					data_history = np.hstack([data_history[1:], [vel_next]])

					vel_mean = distance_calc(vel_current/3.6, vel_ctl/3.6)


				# print(opt_results_v2['flag'][count])
				################################### 存储数据 ###################################	
				################ 存储标志位 ################
				opt_results_v2['flag'].append(flag)

				################ 存储纯优化的数据 ################
				if flag != 1:
					flag_motor_speed_opt = -1
					flag_torque_opt = -1
					torque_opt = -1
					motor_eff_opt = -1
					energy_opt = -1
					torque_wheel_opt = -1
					motor_speed_opt = -1

				opt_results_v2['flag_motor_speed_opt'].append(flag_motor_speed_opt)
				opt_results_v2['flag_torque_opt'].append(flag_torque_opt)
				opt_results_v2['vel_opt'].append(vel_optimize) 
				opt_results_v2['torque_opt'].append(torque_opt)  
				opt_results_v2['gear_opt'].append(gear_optimize)
				opt_results_v2['motor_eff_opt'].append(motor_eff_opt)
				opt_results_v2['energy_opt'].append(energy_opt)
				opt_results_v2['torque_wheel_opt'].append(torque_wheel_opt)
				opt_results_v2['motor_speed_opt'].append(motor_speed_opt)

				################ 存储原始数据 ################
				opt_results_v2['flag_motor_speed_dmd'].append(flag_motor_speed_dmd)
				opt_results_v2['flag_torque_dmd'].append(flag_torque_dmd)
				opt_results_v2['vel_dmd'].append(vel_dmd)
				opt_results_v2['torque_dmd'].append(torque_seq_dmd[0])
				opt_results_v2['gear_dmd'].append((np.where(gears_in_use == gear_dmd)[0])[0] + 1)
				opt_results_v2['motor_eff_dmd'].append(motor_eff_seq_dmd[0])

				opt_results_v2['torque_wheel_dmd'].append(torque_wheel_dmd)
				opt_results_v2['motor_speed_dmd'].append(motor_speed_dmd)

				################ 存储实际执行的数据（兼顾驾驶意图的） ################
				opt_results_v2['flag_motor_speed_ctl'].append(flag_motor_speed_ctl)
				opt_results_v2['flag_torque_ctl'].append(flag_torque_ctl)
				opt_results_v2['vel_ctl'].append(vel_ctl)
				opt_results_v2['torque_ctl'].append(torque_seq_ctl[0])
				opt_results_v2['gear_ctl'].append((np.where(gears_in_use == gear_ctl)[0])[0] + 1)
				opt_results_v2['motor_eff_ctl'].append(motor_eff_seq_ctl[0])
				opt_results_v2['energy_ctl'].append(energy_ctl)
				opt_results_v2['torque_wheel_ctl'].append(torque_wheel_ctl)
				opt_results_v2['motor_speed_ctl'].append(motor_speed_ctl)
				
				opt_results_v2['vel_mean'].append(vel_mean)

				################# 存储权重 ################
				opt_results_v2['W'].append(W)
				opt_results_v2['w1'].append(w1)
				# ################ 预测车速 ################
				opt_results_v2['vel_pred'].append(vel_pred[0])

				
			opt_results_v2['energy_total_opt'] = sum(opt_results_v2['energy_opt']) / 3600 / 1000  # kw*h
			opt_results_v2['single_vel_opt'] = [x[0] if isinstance(x, np.ndarray) else x for x in opt_results_v2['vel_opt']]
			opt_results_v2['single_torque_opt'] = [x[0] if isinstance(x, np.ndarray) else x for x in opt_results_v2['torque_opt']]
			opt_results_v2['single_gear_opt'] = [x[0] if isinstance(x, np.ndarray) else x for x in opt_results_v2['gear_opt']]
			opt_results_v2['single_motor_eff_opt'] = [x[0] if isinstance(x, np.ndarray) else x for x in opt_results_v2['motor_eff_opt']]

			opt_results_v2['energy_total_ctl'] = sum(opt_results_v2['energy_ctl']) / 3600 / 1000  # kw*h
			opt_results_v2['distance'] = sum(opt_results_v2['vel_mean'])

			res.append(opt_results_v2)

			ori_results = {}
			ori_results['vel'] = []
			ori_results['gear'] = []
			ori_results['torque'] = []			
			ori_results['energy'] = []
			ori_results['motor_eff'] = []
			ori_results['energy_total'] = 0
			ori_results['vel_mean'] = []
			ori_results['torque_wheel'] = []

			for i in progressbar.progressbar(range(n_steps_in, v.size - n_steps_out)):
			# for i in progressbar.progressbar(range(n_steps_in, n_steps_in+20)):
				vel_current = v[i - 1] / 3.6
				vel_next = v[i] / 3.6
				gear_next = gears_in_use[int(g[i] - 1)]
				(energy, motor_seq, motor_eff_seq, _,_,_) = energy_and_motor_eff_calc(v[i-1:i+1]/3.6, np.array([gear_next]), per_meter=False)
				vel_mean = (vel_next + vel_current) / 2
				ori_results['vel'].append(v[i])
				ori_results['gear'].append(g[i])
				ori_results['torque'].append(motor_seq[0])
				ori_results['energy'].append(energy)
				ori_results['torque_wheel'].append(motor_seq[0] * gear_next * i0 * eff_diff * eff_cpling)
				ori_results['motor_eff'].append(motor_eff_seq[0])
				ori_results['vel_mean'].append(vel_mean)
			ori_results['energy_total'] = sum(ori_results['energy']) / 3600 / 1000

			#%% distance
			ori_results['distance'] = sum(ori_results['vel_mean'])
			ori.append(ori_results)
	# results_ori_noW[string] = ori_results

with open('res.pickle', 'wb') as f:
	pickle.dump([res, ori], f)




with open('opt_results_v2.pickle', 'wb') as f:
 	pickle.dump([opt_results_v2, ori_results],f)



# with open('opt_results_v2.pickle','rb') as f:
# 	[opt_results_v2,ori_results] = pickle.load(f)
# %%
