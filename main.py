import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from tkinter.filedialog import askopenfilename
from tkinter import Tk

# Load the CSV file
Tk().withdraw()  # Hide the root window
file_path = askopenfilename(title="Select CSV File", filetypes=[("CSV files", "*.csv")])
data = pd.read_csv(file_path)

# Step 1: Clean column names
data.columns = data.columns.str.strip()

# Step 2: Convert 'Jumlah Investasi' to numeric
data['Jumlah Investasi'] = pd.to_numeric(
    data['Jumlah Investasi']
        .str.replace('.', '', regex=False)  # Remove thousand separator
        .str.replace(',', '.', regex=False)  # Replace decimal comma with dot
        .str.strip(),
    errors='coerce'
).fillna(0)  # Replace invalid entries with 0

# Convert to thousands
data['Jumlah Investasi'] = data['Jumlah Investasi'] / 1000


# Step 3: Convert 'Tanggal Transaksi' to datetime
data['Tanggal Transaksi'] = pd.to_datetime(data['Tanggal Transaksi'], format='%d %b %Y')

# Step 4: Extract month and year
data['Month'] = data['Tanggal Transaksi'].dt.to_period('M')

# Step 5: Calculate Buy and Sell Totals for each month
buy_data = data[data['Transaksi'].isin(['Pembelian', 'Kupon'])]
sell_data = data[data['Transaksi'] == 'Penjualan']

print(buy_data.to_string())
print(sell_data.to_string())

buy_monthly = buy_data.groupby('Month')['Jumlah Investasi'].sum().reset_index()
sell_monthly = sell_data.groupby('Month')['Jumlah Investasi'].sum().reset_index()

print(buy_monthly.to_string())
print(sell_monthly.to_string())

# Merge the Buy and Sell totals
monthly_summary = pd.merge(buy_monthly, sell_monthly, on='Month', how='outer', suffixes=('_Buy', '_Sell'))
monthly_summary['Month'] = monthly_summary['Month'].astype(str)
monthly_summary = monthly_summary.fillna(0)
print(monthly_summary)
# Step 6: Prepare bar positions
x = np.arange(len(monthly_summary))  # X positions for the months
bar_width = 0.4  # Width of the bars

# Step 7: Plot side-by-side bars
plt.figure(figsize=(30, 8))
plt.bar(x - bar_width / 2, monthly_summary['Jumlah Investasi_Buy'], width=bar_width, label='Buy Total', color='green')
plt.bar(x + bar_width / 2, monthly_summary['Jumlah Investasi_Sell'], width=bar_width, label='Sell Total', color='red')

# Add labels to each bar
for i, (buy, sell) in enumerate(zip(monthly_summary['Jumlah Investasi_Buy'], monthly_summary['Jumlah Investasi_Sell'])):
    plt.text(x[i] - bar_width / 2, buy + 500, f'{buy:,.0f}', ha='center', va='bottom', color='green', fontsize=10)
    plt.text(x[i] + bar_width / 2, sell + 500, f'{sell:,.0f}', ha='center', va='bottom', color='red', fontsize=10)

# Step 8: Overlay the line chart with gradient coloring
total_investment = monthly_summary['Jumlah Investasi_Buy'] - monthly_summary['Jumlah Investasi_Sell']
colors = ['blue' if total_investment[i] - total_investment[i - 1] > 0 else 'blue' for i in range(1, len(total_investment))]
colors.insert(0, 'blue')  # First segment has no gradient

for i in range(len(x) - 1):
    plt.plot(
        x[i:i+2],
        total_investment[i:i+2],
        marker='o',
        linestyle='-',
        color=colors[i],
        label=None if i > 0 else 'Net Investment (Buy - Sell)'
    )

# Add alternating labels for the line chart
for i, value in enumerate(total_investment):
    label_position = 'bottom' if i % 2 == 0 else 'top'
    offset = -150 if label_position == 'bottom' else 150
    plt.text(x[i], value + offset, f'{value:,.0f}', ha='center', va='center', fontsize=10, color='blue')

# Step 9: Add cumulative savings line
cumulative_savings = np.cumsum(total_investment)
plt.plot(x, cumulative_savings, marker='s', linestyle='--', color='orange', label='Cumulative Savings')

# Add labels for cumulative savings
for i, value in enumerate(cumulative_savings):
    plt.text(x[i], value + 300, f'{value:,.0f}', ha='center', va='bottom', fontsize=10, color='orange')

# Step 10: Customize the plot
plt.title('Monthly Investment Summary with Buy and Sell Totals', fontsize=16)
plt.xlabel('Month', fontsize=12)
plt.ylabel('Amount (IDR)', fontsize=12)
plt.xticks(x, monthly_summary['Month'], rotation=45, fontsize=10)
plt.yticks(fontsize=10)
plt.grid(True, linestyle='--', alpha=0.7)
plt.legend(fontsize=12)
plt.tight_layout()

# Show the plot
plt.show()
