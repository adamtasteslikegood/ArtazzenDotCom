import random
import time
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from  random import randint

i = 0

pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', 1000)
# populate a df with a set of random numbers to demonstrate the different ways to use the imported libraries pretty
# print df.head, info and plot a few style graphs nesting examples inside themselves as they are displayed©
df = pd.DataFrame(np.random.randn(10, 4))


# print df.head, info and plot a few style graphs nesting examples inside themselves as they are displayed
df2 = pd.DataFrame(np.random.randn(10, 4), columns=['A', 'B', 'C', 'D'])

# Display DataFrame head and info
print("DataFrame Head:")
print(df.head())
print("\nDataFrame Info:")
print(df.info())
print("\nDataFrame Description:")
print(df.describe())

# Create nested subplots with different graph styles
fig, axes = plt.subplots(2, 2, figsize=(12, 10))
fig.suptitle('Nested Graph Examples', fontsize=16)

# Line plot
axes[0, 0].plot(df.index, df['A'], label='A', marker='o')
axes[0, 0].plot(df.index, df['B'], label='B', marker='s')
axes[0, 0].set_title('Line Plot')
axes[0, 0].legend()
axes[0, 0].grid(True)

# Bar plot
df[['A', 'B']].plot(kind='bar', ax=axes[0, 1], alpha=0.7)
axes[0, 1].set_title('Bar Plot')

# Scatter plot
axes[1, 0].scatter(df['A'], df['C'], alpha=0.6, c='blue', label='A vs C')
axes[1, 0].scatter(df['B'], df['D'], alpha=0.6, c='red', label='B vs D')
axes[1, 0].set_title('Scatter Plot')
axes[1, 0].legend()

# Box plot
df.boxplot(ax=axes[1, 1])
axes[1, 1].set_title('Box Plot')

plt.tight_layout()
plt.show()

while i < 10:
    for i in range(10):
        df = pd.DataFrame(np.random.randn(10, 4))
        print(df)

    print(randint(1, 10))
    i += 1

    if i < 10:
        print(randint(1, 10))


for i in range(10):
    print(randint(1, 10))

    if i < 10:
        print(randint(1, 10))

df = pd.concat([pd.DataFrame(np.random.randn(10, 4)), pd.DataFrame(np.random.randn(10, 4))], axis=1)
df.columns = ['A', 'B', 'C', 'D']

print(df2)

