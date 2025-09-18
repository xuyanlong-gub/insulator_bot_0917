import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 读取CSV文件
df = pd.read_csv(r'D:\workspace\绝缘子清洗机器人\项目代码\草稿版本0908-3\insulator_bot\logs\sample.csv')

# 设置中文字体支持
plt.rcParams['font.sans-serif'] = ['SimHei', 'FangSong', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题


# 绘制flag列
plt.figure(figsize=(12, 6))
plt.plot(df.index, df['flag'], marker='o', markersize=2, linewidth=1)
plt.title('Flag列数据变化')
plt.xlabel('采样点')
plt.ylabel('Flag值')
plt.grid(True, alpha=0.3)
plt.show()
