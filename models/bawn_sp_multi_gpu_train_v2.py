from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from datetime import datetime
import os.path
import re
import time
import pickle
import argparse 

import numpy as np
from six.moves import xrange  # pylint: disable=redefined-builtin
import tensorflow as tf
import bawn

LOG_DIR = '/tmp'
NUM_GPUS = 1
LOG_DEVICE_PLACEMENT = False


# Constants describing the training process.
MOVING_AVERAGE_DECAY = 0.9999
INITIAL_LEARNING_RATE = 0.001
ANNEALING_RATE = 0.996
MAX_STEPS = 800000
NUM_STEPS_PER_DECAY = 1000
PERIOD_SUMMARY = 120
PERIOD_CHECKPOINT = 600


def tower_loss(scope, segments, labels):
    """Calculate the total loss on a single tower running the BAWN model.
    Args:
      scope: unique prefix string identifying the BAWN tower, e.g. 'tower_0'
    Returns:
       Tensor of shape [] containing the total loss for a batch of data
    """
    #segments = tf.Print(segments, [segments[0,4094:]], message=scope, summarize=10)
    #labels = tf.Print(labels, [labels[0,:-1]], message='labels', summarize=10)
    
    # Build inference Graph.
    logits = bawn.model_simple(segments)
    #bawn._activation_summary(logits)
    #bawn._activation_summary(tf.one_hot(labels,256,axis=1,dtype=tf.float32))
    #logits = tf.Print(logits, [logits[0,:-1]], message='logits', summarize=10)
        
    # Build the portion of the Graph calculating the losses. Note that we will
    # assemble the total_loss using a custom function below.
    logits = tf.transpose(logits, perm=[0, 2, 1])
    _ = bawn.loss(logits, labels)
    #print(logits.shape)
    #print(labels.shape)
  
    # Assemble all of the losses for the current tower only.
    losses = tf.get_collection('losses', scope)
  
    # Calculate the total loss for the current tower.
    total_loss = tf.add_n(losses, name='total_loss')
    
    # Attach a scalar summary to all individual losses and the total loss; do the
    # same for the averaged version of the losses.
    for l in losses + [total_loss]:
        # Remove 'tower_[0-9]/' from the name in case this is a multi-GPU training
        # session. This helps the clarity of presentation on tensorboard.
        loss_name = re.sub('%s_[0-9]*/' % bawn.TOWER_NAME, '', l.op.name)
        tf.summary.scalar(loss_name, l)
        
    return total_loss


def average_gradients(tower_grads):
    """Calculate the average gradient for each shared variable across all towers.
    Note that this function provides a synchronization point across all towers.
    Args:
      tower_grads: List of lists of (gradient, variable) tuples. The outer list
        is over individual gradients. The inner list is over the gradient
        calculation for each tower.
    Returns:
       List of pairs of (gradient, variable) where the gradient has been averaged
       across all towers.
    """
    average_grads = []
    for grad_and_vars in zip(*tower_grads):
        # Note that each grad_and_vars looks like the following:
        #   ((grad0_gpu0, var0_gpu0), ... , (grad0_gpuN, var0_gpuN))
        grads = []
        for g, _ in grad_and_vars:
            # Add 0 dimension to the gradients to represent the tower.
            expanded_g = tf.expand_dims(g, 0)
      
            # Append on a 'tower' dimension which we will average over below.
            grads.append(expanded_g)
    
        # Average over the 'tower' dimension.
        grad = tf.concat(axis=0, values=grads)
        grad = tf.reduce_mean(grad, 0)
    
        # Keep in mind that the Variables are redundant because they are shared
        # across towers. So .. we will just return the first tower's pointer to
        # the Variable.
        v = grad_and_vars[0][1]
        grad_and_var = (grad, v)
        average_grads.append(grad_and_var)
    return average_grads

#def data_generator(data_segments, data_labels):
    ## initialize training data
#    while True:
#        for i in range(0, data_segments.shape[0], 1000):
#            yield ({'segments_initializer': data_segments[i*1000:(i+i)*1000], 'labels_initializer': data_labels[i*1000:(i+1)*1000]})

#def GetDataSlices(x, data_segments, data_labels):
#    return (data_Segments[sorted(x)], data_labels[sorted(x)])

def train():
    """Train BAWN for a number of steps."""
    with tf.Graph().as_default(), tf.device('/device:CPU:0'):
        # training data initializers
        #with tf.name_scope('input'):
            #segments_initializer, labels_initializer, input_segments, input_labels \
            #= bawn.data_initializer_simple(data_segments, data_labels)
            
            #segment, label = tf.train.slice_input_producer([input_segments, input_labels])
        
        shuffle_size = 1000
        batch_size = bawn.BATCH_SIZE
        repeat_size = None
        with tf.name_scope('input'):
            dataset = tf.data.Dataset.from_tensor_slices(np.arange(data_segments.shape[0]))
            dataset = dataset.shuffle(shuffle_size)
            dataset = dataset.batch(batch_size)
            dataset = dataset.repeat(repeat_size)
            dataset = dataset.map(lambda x: (data_Segments[sorted(x)], data_labels[sorted(x)]))
            iter = dataset.make_initializable_iterator()
            segments, labels = iter.get_next()

        # Create a variable to count the number of train() calls. This equals the
        # number of batches processed * num_gpus.
        global_step = tf.train.create_global_step()
        
        # Decay the learning rate based on the number of steps.
        lr = tf.train.exponential_decay(INITIAL_LEARNING_RATE, global_step,
                                        NUM_STEPS_PER_DECAY, ANNEALING_RATE, staircase=True)
          
        # Create an optimizer that performs gradient descent.
        opt = tf.train.AdamOptimizer(lr)
        
        # Calculate the gradients for each model tower.
        tower_grads = []
        with tf.variable_scope(tf.get_variable_scope()):
            for i in xrange(NUM_GPUS):
                with tf.device('/device:GPU:%d' % i):
                    with tf.name_scope('%s_%d' % (bawn.TOWER_NAME, i)) as scope:
                        # Get batches of images and labels for BAWN.
                        # segments, labels = tf.train.batch([segment, label], batch_size=bawn.BATCH_SIZE)   
                        
                        # Calculate the loss for one tower of the BAWN model. This function
                        # constructs the entire BAWN model but shares the variables across
                        # all towers.
                        loss = tower_loss(scope, segments, labels)
            
                        # Reuse variables for the next tower.
                        tf.get_variable_scope().reuse_variables()
            
                        # Retain the summaries from the final tower.
                        summaries = tf.get_collection(tf.GraphKeys.SUMMARIES, scope)
            
                        # Calculate the gradients for the batch of data on this BAWN tower.
                        grads = opt.compute_gradients(loss)
            
                        # Keep track of the gradients across all towers.
                        tower_grads.append(grads)
        
        # We must calculate the mean of each gradient. Note that this is the
        # synchronization point across all towers.
        grads = average_gradients(tower_grads)
    
        # Add a summary to track the learning rate.
        summaries.append(tf.summary.scalar('learning_rate', lr))
    
            
        # Apply the gradients to adjust the shared variables and increment the global step.
        apply_gradient_op = opt.apply_gradients(grads, global_step=global_step)
        
        # Track the moving averages of all trainable variables.
        variable_averages = tf.train.ExponentialMovingAverage(
                            MOVING_AVERAGE_DECAY, global_step)
        variables_averages_op = variable_averages.apply(tf.trainable_variables())
        
        # Group all updates to into a single train op.
        train_op = tf.group(apply_gradient_op, variables_averages_op)
    
        # Create a saver.
        saver = tf.train.Saver(tf.global_variables(), max_to_keep=10)
    
        # Build the summary operation from the last tower summaries.
        summary_op = tf.summary.merge(summaries, collections=[tf.GraphKeys.SUMMARY_OP])
        
        sess_config = tf.ConfigProto(allow_soft_placement=True,
                                log_device_placement=LOG_DEVICE_PLACEMENT)                        
        
        # Superviser 
        sv = tf.train.Supervisor(logdir=LOG_DIR
                                 ,summary_op=summary_op
                                 ,saver=saver
                                 ,save_model_secs=PERIOD_CHECKPOINT
                                 ,save_summaries_secs=PERIOD_SUMMARY
                                 ,checkpoint_basename='bawn_sp_v2.ckpt')
        
                
        #sess = sv.prepare_or_wait_for_session(config=sess_config)
        
        with sv.managed_session(config=sess_config, start_standard_services=False) as sess:
            ## initialize training data
            #sess.run(segments_initializer,
            #     feed_dict={segments_initializer: data_segments})
            #sess.run(labels_initializer,
            #     feed_dict={labels_initializer: data_labels})
            #print("init....")
            sess.run(iter.initializer)
            #sess.run(tf.global_variables_initializer())
            print('Starting services and queue runners...')
            # start the queue runner after feed_dict so that the desired elements are enqueued
            sv.start_standard_services(sess)
            sv.start_queue_runners(sess)
                
            costs = []
            start = sess.run(global_step)
            for step in xrange(start, MAX_STEPS):
                if sv.should_stop():
                    print('SB!!!!!!!!!')
                    break
                start_time = time.time()
                _, loss_value = sess.run([train_op, loss])
                duration = time.time() - start_time
            
                assert not np.isnan(loss_value), 'Model diverged with loss = NaN'
                
                if loss_value < 0.01:
                    summary_str = sess.run(summary_op)
                    sv.summary_computed(sess, summary_str)
                    #break                    
                                      
                if step % 10 == 0:
                    num_examples_per_step = bawn.BATCH_SIZE * NUM_GPUS
                    examples_per_sec = num_examples_per_step / duration
                    sec_per_batch = duration / NUM_GPUS
            
                    format_str = ('%s: step %d, loss = %.2f (%.1f examples/sec; %.3f '
                                  'sec/batch)')
                    print (format_str % (datetime.now(), step, loss_value,
                                       examples_per_sec, sec_per_batch))
                    costs.append(loss_value)
                    pickle.dump(costs, open(os.path.join(LOG_DIR, 'losses.p'), "wb"))
      
            
if __name__ == '__main__':
    parser = argparse.ArgumentParser()  
    parser.add_argument("LOG_DIR", help="LOG_DIR")
    parser.add_argument("NUM_GPUS", help="NUM_GPUS", type=int)
    args = parser.parse_args()
    LOG_DIR = args.LOG_DIR
    NUM_GPUS = args.NUM_GPUS
    with tf.device('/device:CPU:0'):
        data_segments, data_labels, f_in, f_tgt = bawn.load_data_simple('noisy_train.mat','target_train.mat')
    train()
    f_in.close()
    f_tgt.close()
