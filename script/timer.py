import schedule
import time
import sign as sign

if __name__ == '__main__':
  for t in sign.config['times']:
    schedule.every().day.at(t['time']).do(sign.main)
    sign.log('已开启定时任务——执行时间：' + t['time'])
  # While循环定时执行任务
  while True:
    # 根据上述任务调度安排执行任务
    schedule.run_pending()
    time.sleep(1)