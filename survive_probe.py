import time
open('reports/rq1b_runs/run_00/tmp/survive_test.txt', 'w').write('started')
time.sleep(60)
open('reports/rq1b_runs/run_00/tmp/survive_test.txt', 'a').write('finished')
