import pickle
import numpy as np
import matplotlib.pyplot as plt

# check data correctness
with open('res.pickle', 'rb') as f:
    res, ori = pickle.load(f)

for i, (a, b) in enumerate(zip(res, ori)):
    if len(a['energy_ctl']) != len(b['energy']):
        print(i)

# energy and distance boxplot
e = np.array([x['energy_total_ctl'] for x in res])
eo = np.array([x['energy_total'] for x in ori])
pct_e = (eo - e) / eo
plt.boxplot(pct_e)
plt.title('energy opt pct')
plt.show()

d = np.array([x['distance'] for x in res])
do = np.array([x['distance'] for x in ori])
pct_d = (do - d) / do
plt.boxplot(pct_d)
plt.title('distance red pct')
plt.show()

# pct min
pct_e_sorted = np.sort(pct_e)
for pct in pct_e_sorted:
    idx = np.argwhere(pct == pct_e)
    print(f'pct e: {pct}, pct d: {pct_d[idx]}')
    plt.plot(res[idx[0][0]]['vel_ctl'], label='opt')
    plt.plot(ori[idx[0][0]]['vel'], label='ori')
    plt.title('vel comparison')
    # plt.text(f'pct e: {pct}, pct d: {pct_d[idx]}')
    plt.legend()
    plt.show()