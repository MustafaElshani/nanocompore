# # -*- coding: utf-8 -*-
#
# #~~~~~~~~~~~~~~IMPORTS~~~~~~~~~~~~~~#
# # Std lib
# import logging
# import queue
# import threading
# from collections import defaultdict
# from os import makedirs
# import mmap
# import argparse
# import pickle
# import os
# import csv
# from pathlib import Path
#
# # Third party
# import pysam
# from tqdm import tqdm, tqdm_notebook
# import numpy as np
# from bedparse import bedline
#
# # Local package
# from nanocompore.txCompare import txCompare
# from nanocompore.helper_lib import mkdir, access_file
# from nanocompore.Whitelist import Whitelist
# from nanocompore.NanocomporeError import NanocomporeError
#
# # Logger setup
# logging.basicConfig(level=logging.INFO, format='%(message)s')
# logger = logging.getLogger(__name__)
# logLevel_dict = {"debug":logging.DEBUG, "info":logging.INFO, "warning":logging.WARNING}
#
# #~~~~~~~~~~~~~~MAIN FUNCTION~~~~~~~~~~~~~~#
# class SampComp (object):
#     """ Produce useful results. => Thanks Tommaso ! That's a very *useful* comment :P """
#
#     def __init__(self,
#         s1_fn,
#         s2_fn,
#         whitelist,
#         outfolder = None,
#         nthreads = 4,
#         checkpoint = True,
#         logLevel = "info",
#         padj_threshold = 0.1):
#
#         """
#         Main routine that starts readers and consumers
#             s1_fn: path to a nanopolish eventalign collapsed file corresponding to sample 1
#             s2_fn: path to a nanopolish eventalign collapsed file corresponding to sample 2
#             outfolder: path to folder where to save output
#             nthreads: number of consumer threads
#             whitelist_dict: Dictionnary generated by nanocopore whitelist function
#         """
#         # Set logging level
#         logger.setLevel (logLevel_dict.get (logLevel, logging.WARNING))
#
#         logger.info ("Initialise and checks options")
#
#         self.__checkpoint = checkpoint
#         self.__padj_threshold = padj_threshold
#
#         if not isinstance (whitelist, Whitelist):
#             raise NanocomporeError("Whitelist is not valid")
#         self.__whitelist = whitelist
#
#         # Check that input files is readeable
#         for fn in (s1_fn, s2_fn):
#             access_file (fn)
#         self.s1_fn = s1_fn
#         self.s2_fn = s2_fn
#
#         # Check that output folder doesn't exist and create it
#         if self.__checkpoint:
#             mkdir (outfolder)
#         self.__outfolder = outfolder
#
#         # Check thread number is valid
#         if nthreads < 3:
#             raise NanocomporeError("Number of threads not valid")
#         self.n_consumer_threads = nthreads-2
#
#     def __call__ (self):
#
#         # Start sample processing
#         logger.info ("Compare samples for all intervals in whitelist")
#
#         # Init Multiprocessing variables
#         in_q = mp.Queue (maxsize = 1000)
#         out_q = mp.Queue (maxsize = 1000)
#
#         # Define processes
#         ps_list = []
#         ps_list.append (mp.Process (target=self._list_candidate, args=(in_q,)))
#         for i in range (self.threads):
#             ps_list.append (mp.Process (target=self._process, args=(in_q, out_q)))
#         ps_list.append (mp.Process (target=self._write_output, args=(out_q,)))
#
#         # Start processes and block until done
#         try:
#             for ps in ps_list:
#                 ps.start ()
#             for ps in ps_list:
#                 ps.join ()
#
#         # Kill processes if early stop
#         except (BrokenPipeError, KeyboardInterrupt) as E:
#             if self.verbose: stderr_print ("Early stop. Kill processes\n")
#             for ps in ps_list:
#                 ps.terminate ()
#
#
#
#         # Final results
#         self.__results = []
#
#         # Data read by the readers
#         self.data_f1 = dict()
#         self.data_f2 = dict()
#
#         # Set containg names of already processed transcripts
#         self.processed=set()
#
#         self.__reader1 = threading.Thread (name="reader1", target=self.__parse_events_file, args=(self.s1_fn, self.data_f1, 1))
#         self.__reader2 = threading.Thread (name="reader2", target=self.__parse_events_file, args=(self.s2_fn, self.data_f2, 2))
#
#         consumers=[]
#         for i in range(self.n_consumer_threads):
#             consumers.append(threading.Thread(name="consumer%s"%i, target=self.__consumer))
#
#         self.__reader1.start()
#         self.__reader2.start()
#
#         for c in consumers:
#             c.start()
#
#         # Wait for the readers to complete
#         self.__reader1.join()
#         self.__reader2.join()
#         # Wait for the queue to be empty
#         logger.warning("Wainting for processing queue to be empty")
#         self.__main_queue.join()
#         # Wait for the consumers to complete
#         for c in consumers:
#             c.join()
#
#
#         # Print results
#         if self.__checkpoint:
#             with open(self.__outfolder+'/results.p', 'wb') as pfile:
#                 pickle.dump(self.__results, pfile)
#
#     def __parse_events_file (self, file, data, barPos=1):
#         """ Parse an events file line by line and extract lines
#         corresponding to the same transcripts. When a transcript
#         is read entirely, add its name to the __main_queue and the
#         the data to data. """
#         tx=""
#         block=[]
#         # Reading the whole file to count lines is too expensive. 128bytes is the average line size in the collapsed events files
#         bar=self.__mytqdm(total=int(os.stat(file).st_size/128), desc="File%s progress" % barPos, position=barPos, unit_scale=True, disable=self.logLevel in [logging.DEBUG, logging.INFO])
#         with open(file, "r") as f:
#             for l in f:
#                 line=l.split("\t")
#                 bar.update()
#                 if(line[0] != "contig" and line[0] in self.tx_whitelist):
#                     if line[0]==tx:
#                         block.append(line)
#                         tx=line[0]
#                     else:
#                         if len(block)!=0:
#                             data[tx]=block
#                             self.__main_queue.put(tx)
#                         logger.debug("Finished processing (%s)" % (tx))
#                         block=[line]
#                         tx=line[0]
#         if len(block)!=0:
#             data[tx]=block
#             self.__main_queue.put(tx)
#             logger.debug("Finished processing (%s)" % (tx))
#         bar.close()
#
#     def __consumer(self):
#         while True:
#             if self.__main_queue.empty() and not self.__reader1.is_alive() and not self.__reader2.is_alive():
#                 logger.debug("Queue is empty and readers have finished, terminating")
#                 break
#             # This timeout prevents threads to get stuck in case the
#             # queue gets empty between the check above and the get
#             try:
#                 tx = self.__main_queue.get(timeout=3)
#             except queue.Empty:
#                 continue
#
#             # If the data is not ready
#             if tx not in self.data_f1.keys() or tx not in self.data_f2.keys():
#                 # If one of the readers is still alive return tx to the queue
#                 if self.__reader1.is_alive() or self.__reader2.is_alive():
#                     self.__main_queue.put(tx)
#                     logger.debug("Returning (%s) to Q. Q has (%s) items" % (tx, self.__main_queue.qsize()))
#                 # Else, if either of the readers has finished, remove the task from queue
#                 else:
#                     logger.debug("Discarding (%s) because readers have terminated and data not present" % (tx))
#                 self.__main_queue.task_done()
#
#             # If the data is ready
#             else:
#                 logger.debug("Picked (%s) from Q. Q has (%s) items." % (tx, self.__main_queue.qsize()))
#                 # Acquire lock to make sure nothing is written to processed after we check
#                 self.__lock.acquire()
#                 if tx not in self.processed:
#                     self.processed.add(tx)
#                     self.__lock.release()
#                     self.__results.append(self.process_tx(self.data_f1.pop(tx), self.data_f2.pop(tx)))
#                 else:
#                     self.__lock.release()
#                 self.__main_queue.task_done()
#
#     def process_tx(self, data1, data2):
#         if data1[0][0] != data2[0][0]:
#             print("Error")
#         else: tx=data1[0][0]
#         logger.info("Processed %s" % (tx))
#         return(txCompare([tx, [data1, data2]]).significant(self.__padj_threshold))
#         #return([tx, [data1, data2]])
#
#     @staticmethod
#     def __mytqdm(**kwargs):
#         try:
#             if get_ipython().__class__.__name__ == 'ZMQInteractiveShell':
#                 return tqdm_notebook(**kwargs)
#             else:
#                 return tqdm(**kwargs)
#         except NameError:
#             return tqdm(**kwargs)
#
#     def print_results(self, bedfile=None, outfile=None):
#         """ Return the list of significant regions.
#         If a bed file is provided also return the genome coordinates """
#         b=[]
#         if bedfile is None:
#             for i in [ i for k in self.__results for i in k]:
#                 b.append(i)
#         else:
#             bed=dict()
#             sig = { i[0]+"##"+i[1] for k in self.__results for i in k }
#             r = []
#             with open(bedfile, 'r') as tsvfile:
#                 for line in tsvfile:
#                     line = line.split('\t')
#                     tx_name=line[3]
#                     if(tx_name in sig):
#                         bed[tx_name] = bedline(line)
#             for i in [ i for k in self.__results for i in k]:
#                 name=i[0]+"##"+i[1]
#                 chr_coord=bed[name].tx2genome(i[4])
#                 b.append(["chr"+i[2], chr_coord, chr_coord+5, name+"##"+str(i[4]), -np.log10(i[5])*100])
#         if outfile is None:
#             for i in b:
#                 print(*i, sep="\t")
#         else:
#             with open(outfile, 'w', newline='') as f:
#                 try:
#                     wr = csv.writer(f, quoting=csv.QUOTE_NONE, delimiter="\t")
#                     for i in b:
#                         wr.writerow(i)
#                 except:
#                     raise NanocomporeError("Error writing to file")
