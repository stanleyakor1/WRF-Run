import os
import sys 
import datetime 
import subprocess
import time 
import glob 
import xarray as xr
import numpy as np
import time 
import traceback
import logging
import threading 
logger = logging.getLogger(__name__)


# function decorators 
def passfail(func):
	def wrapped_func(*args, **kwargs):
		try:
			func(*args)
			message = "{} Passed".format(str(func))
			return (True,message)
		except Exception as e:
			trace_string =  traceback.format_exc()	
			error_message = "{} Failed with the following Error: {}\n {}".format(str(func), e, trace_string)
			return (False, error_message)
	return wrapped_func


def timer(function):
	# simple decorator to time a function
	def wrapper(*args,**kwargs):
		t1 = datetime.datetime.now()
		wrapped_function = function(*args,**kwargs)
		t2 = datetime.datetime.now()
		dt = (t2 - t1).total_seconds()/60   # time in minutes
		logging.info('function {} took {} minutes complete'.format(function.__name__, dt))	
		return wrapped_function
	return wrapper

# functions 
def CleanUp(path):
	# remove files from the run directory 
	cwd = os.getcwd()
	os.chdir(path)
	removeList = ["*LDASOUT*"
		    ,"*CHRTOUT*"
		    ,"*RTOUT*"
		    ,"*LSMOUT*"
		    ,"*diag_hydro*"
		    ,"*HYDRO_RST*"
	            "log_wrf_hydro*"]
	
	logger.info('cleaning up model run directory ({})'.format(path)) 
	for removeMe in removeList:
		for singleFile in glob.glob(removeMe):
			try:
				os.remove(singleFile)
			except:
				pass
	# move back to o.g. dir
	os.chdir(cwd)

def SystemCmd(cmd):
	# issue system commands 
	proc = subprocess.Popen([cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
	out,err = proc.communicate()
	return out.split(),err

def Submit(subname, scheduler):
	if scheduler == 'PBS':
		cmd = 'jobid=$(qsub {});echo $jobid'.format(subname)	
		proc = subprocess.Popen([cmd], stdout=subprocess.PIPE, shell=True)	
		jobid,err = proc.communicate()
		# DOES THIS WORK FOR PBS????
		logger.info("submitting job: {}".format(cmd))
		jobid = jobid.decode("utf-8").rstrip()
		logger.info('jobid: {}'.format(jobid))
		return jobid,err
	if scheduler == 'SLURM':
		cmd = 'sbatch --parsable {}'.format(subname)
		proc = subprocess.Popen([cmd], stdout=subprocess.PIPE, shell=True)	
		jobid,err = proc.communicate()
		# DOES THIS WORK FOR PBS????
		logger.info("submitting job: {}".format(cmd))
		return jobid.decode("utf-8").rstrip(),err

	if scheduler not in ['PBS','SLURM']:
		logger.error()
		raise Exception('unknown scheduler type {}'.format(scheduler))
		

def WaitForJob(jobid,user,scheduler):
	# commands are slightly different for the 2 
	# regardless of scheduler, each command queries the queue and 
	# finds all of the job ids that match the username 
	# the python process creates a list of those job ids (different than job names)
	# and tries to match them with the 'jobid' argument that gets passed in
	# the code will wait until none of the jobs in the queue match the jobid passed in 
	if scheduler == 'PBS':
		chid = "qstat | grep {} | sed \"s/^ *//\" | cut -d' ' -f1".format(user)   
			# the qstat -u option parses the jobname oddly 
	
	if scheduler == 'SLURM':
		chid = "squeue -u {} | sed \"s/^ *//\" | cut -d' ' -f1".format(user)   
	
	still_running = 1     # start with 1 for still running 
	while still_running == 1:
		logger.info('wait for job')
		# command
		logger.info(chid)	
		# run command and parse output 
		chidout, chiderr = SystemCmd(chid)    
		chidout = [i.decode("utf-8") for i in chidout]
		
		# decode the error, and mange error output --- the qstat 
		# command can sometimes time out 
		error = chiderr.decode("utf-8")
		if error != '': # the error string is non-empty
			logger.error("error encountered in qstat --- {}".format(error)
			logger.error("wait additional 20s before retry")
			time.sleep(20)
			# ????? HOW DO WE HANDLE THIS ERROR ????? 
			# Current solution is just to wait longer.... 
			# unclear what the best option might be
		 
		# happy path --- everything goes correctly 
		logger.info(chidout)
		# convert the id to an integer
		# the length of the list. should be zero or one. one means the job ID is found 
		still_running_list = list(filter(lambda x: x == jobid, chidout))
		still_running = len(still_running_list)
		logger.info('jobID {} is still running...'.format(still_running_list))
		logger.info('sleep for 10 seconds')
		time.sleep(10)
	
	if scheduler not in ['PBS','SLURM']:
		#!!!! THIS SHOULD BE CAUGHT WAY BEFORE THIS POINT!!!!
		logger.error()
		raise Exception('unknown scheduler type {}'.format(scheduler))

def formatDate(dstr):
	if type(dstr) == str:
		return datetime.datetime.strptime(dstr, '%Y-%m-%d')
	if type(dstr) == datetime.datetime:
		return dstr
	

def GenericWrite(readpath,replacedata,writepath):
	# path to file to read 
	# data dictionary to put into file
	# path to the write out file 
	with open(readpath, 'r') as file:
	    filedata = file.read()
	    #  
	    # loop thru dictionary and replace items
	for item in replacedata:
	    filedata = filedata.replace(item, str(replacedata[item])) # make sure it's a string 

	# Write the file out again
	with open(writepath, 'w') as file:
	    file.write(filedata)
	# done 


#------------- slightly less generic commands ---------# 
def tail(linenumber, filename):
	# issue a system tail commnad 
	returnString, error = SystemCmd('tail -n {} {}'.format(linenumber, filename))
	returnString = ' '.join([x.decode("utf-8")  for x in returnString])
	return returnString 	

def fetchFile(filepath):
	# wget a file 
	SystemCmd('wget --output-file=logfile {}'.format(filepath)) # CHANGE ME...

@acc.passfail
def log_check(logfile, message):
	string = tail(1, logfile)
	assert message in string, string 

@timer 
def multi_thread(function, mappable):
	# generic function
	# applies given function to list, where a list item 
	# is the ONLY input arg to that function
	thread_chunk_size = 5 
	def divide_chunks(l, n): 
		# looping till length l 
		for i in range(0, len(l), n):  
			yield l[i:i + n] 		  

	# create a list of lists 
	chunked_list = list(divide_chunks(mappable, thread_chunk_size))
	# loop thru the chunked list. max of <thread_chunk_size> threads get opened 
	for chunk in chunked_list:
		threads = [threading.Thread(target=function, args=(item,)) for item in mappable]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join()

