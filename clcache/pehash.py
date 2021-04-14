import sys, threading, multiprocessing
from . __main__ import HashAlgorithm


allfiles = []
results = []

def run():
    cpu = multiprocessing.cpu_count()
    def _run():
        while True:
            try:
                file = allfiles.pop()
            except:
                break
            try:
                results.append('  '.join((HashAlgorithm(open(file,'rb').read()).hexdigest(), file.upper())))
            except:
                pass
    threads = []
    for i in range(cpu):
        t = threading.Thread(target=_run)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    print('\n'.join(results))


def main(argv):
    if len(argv) < 1 : return
    global allfiles
    if len(argv) == 1:
        if argv[0].lower().endswith('.txt'):
            allfiles = open(argv[0],'r').read().splitlines()
            allfiles = set(allfiles)
            run()
        else:
            print(HashAlgorithm(open(argv[0],'rb').read()).hexdigest())

if __name__ == "__main__":
    main(sys.argv[1:])