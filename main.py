from __future__ import division
import os,time,cv2,scipy.io
import tensorflow as tf
import tensorflow.contrib.slim as slim
import numpy as np
import matplotlib.pyplot as plt
from discriminator import build_discriminator
import scipy.stats as st
import argparse


parser = argparse.ArgumentParser()
parser.add_argument("--task", default="reflection_removal", help="path to folder containing images")
parser.add_argument("--data_syn_dir", default="/media/cecilia/DATA/reflection/train/", help="path to synthetic dataset")
parser.add_argument("--data_real_dir", default="/media/cecilia/DATA/reflection/train_real/", help="path to real dataset")
parser.add_argument("--is_hyper", default=1, type=int, help="")
parser.add_argument("--is_training", default=1, help="training or testing")
parser.add_argument("--continue_training", action="store_true", help="search for checkpoint in the subfolder specified by `task` argument")
ARGS = parser.parse_args()


task=ARGS.task
is_training=ARGS.is_training==1
continue_training=ARGS.continue_training
hyper=ARGS.is_hyper==1

# os.system('nvidia-smi -q -d Memory |grep -A4 GPU|grep Free >tmp')
if is_training:
    os.environ['CUDA_VISIBLE_DEVICES']=str(0)
else:
    os.environ['CUDA_VISIBLE_DEVICES']=str(0)
EPS = 1e-12
channel = 64 # number of feature channels to build the model, set to 64

train_syn_root=[ARGS.data_syn_dir]
train_real_root=[ARGS.data_real_dir]
test_syn_root=[ARGS.data_syn_dir.replace("train","test")]
test_real_root=[ARGS.data_real_dir.replace("train","test")]

IMG_EXTENSIONS = [
    '.jpg', '.JPG', '.jpeg', '.JPEG',
    '.png', '.PNG', '.ppm', '.PPM', '.bmp', '.BMP',
]

def is_image_file(filename):
    return any(filename.endswith(extension) for extension in IMG_EXTENSIONS)

def build_net(ntype,nin,nwb=None,name=None):
    if ntype=='conv':
        return tf.nn.relu(tf.nn.conv2d(nin,nwb[0],strides=[1,1,1,1],padding='SAME',name=name)+nwb[1])
    elif ntype=='pool':
        return tf.nn.avg_pool(nin,ksize=[1,2,2,1],strides=[1,2,2,1],padding='SAME')

def get_weight_bias(vgg_layers,i):
    weights=vgg_layers[i][0][0][2][0][0]
    weights=tf.constant(weights)
    bias=vgg_layers[i][0][0][2][0][1]
    bias=tf.constant(np.reshape(bias,(bias.size)))
    return weights,bias
    
def lrelu(x):
    return tf.maximum(x*0.2,x)

def relu(x):
    return tf.maximum(0.0,x)

def identity_initializer():
    def _initializer(shape, dtype=tf.float32, partition_info=None):
        array = np.zeros(shape, dtype=float)
        cx, cy = shape[0]//2, shape[1]//2
        for i in range(np.minimum(shape[2],shape[3])):
            array[cx, cy, i, i] = 1
        return tf.constant(array, dtype=dtype)
    return _initializer

def nm(x):
    w0=tf.Variable(1.0,name='w0')
    w1=tf.Variable(0.0,name='w1')
    return w0*x+w1*slim.batch_norm(x)

vgg_path=scipy.io.loadmat('../dev_reflection_removal/VGG_Model/imagenet-vgg-verydeep-19.mat')
print("[i] Loaded vgg19 pretrained imagenet")
def build_vgg19(input,reuse=False):
    with tf.variable_scope("vgg19"):
        if reuse:
            tf.get_variable_scope().reuse_variables()
        net={}
        vgg_layers=vgg_path['layers'][0]
        net['input']=input-np.array([123.6800, 116.7790, 103.9390]).reshape((1,1,1,3))
        net['conv1_1']=build_net('conv',net['input'],get_weight_bias(vgg_layers,0),name='vgg_conv1_1')
        net['conv1_2']=build_net('conv',net['conv1_1'],get_weight_bias(vgg_layers,2),name='vgg_conv1_2')
        net['pool1']=build_net('pool',net['conv1_2'])
        net['conv2_1']=build_net('conv',net['pool1'],get_weight_bias(vgg_layers,5),name='vgg_conv2_1')
        net['conv2_2']=build_net('conv',net['conv2_1'],get_weight_bias(vgg_layers,7),name='vgg_conv2_2')
        net['pool2']=build_net('pool',net['conv2_2'])
        net['conv3_1']=build_net('conv',net['pool2'],get_weight_bias(vgg_layers,10),name='vgg_conv3_1')
        net['conv3_2']=build_net('conv',net['conv3_1'],get_weight_bias(vgg_layers,12),name='vgg_conv3_2')
        net['conv3_3']=build_net('conv',net['conv3_2'],get_weight_bias(vgg_layers,14),name='vgg_conv3_3')
        net['conv3_4']=build_net('conv',net['conv3_3'],get_weight_bias(vgg_layers,16),name='vgg_conv3_4')
        net['pool3']=build_net('pool',net['conv3_4'])
        net['conv4_1']=build_net('conv',net['pool3'],get_weight_bias(vgg_layers,19),name='vgg_conv4_1')
        net['conv4_2']=build_net('conv',net['conv4_1'],get_weight_bias(vgg_layers,21),name='vgg_conv4_2')
        net['conv4_3']=build_net('conv',net['conv4_2'],get_weight_bias(vgg_layers,23),name='vgg_conv4_3')
        net['conv4_4']=build_net('conv',net['conv4_3'],get_weight_bias(vgg_layers,25),name='vgg_conv4_4')
        net['pool4']=build_net('pool',net['conv4_4'])
        net['conv5_1']=build_net('conv',net['pool4'],get_weight_bias(vgg_layers,28),name='vgg_conv5_1')
        net['conv5_2']=build_net('conv',net['conv5_1'],get_weight_bias(vgg_layers,30),name='vgg_conv5_2')
        return net

def build(input):
    if hyper:
        print("[i] Hypercolumn ON, building hypercolumn features ... ")
        vgg19_features=build_vgg19(input[:,:,:,0:3]*255.0)
        for layer_id in range(1,6):
            vgg19_f = vgg19_features['conv%d_2'%layer_id]
            input = tf.concat([tf.image.resize_bilinear(vgg19_f,(tf.shape(input)[1],tf.shape(input)[2]))/255.0,input], axis=3)
    else:
        vgg19_features=build_vgg19(input[:,:,:,0:3]*255.0)
        for layer_id in range(1,6):
            vgg19_f = vgg19_features['conv%d_2'%layer_id]
            input = tf.concat([tf.image.resize_bilinear(tf.zeros_like(vgg19_f),(tf.shape(input)[1],tf.shape(input)[2]))/255.0,input], axis=3)
    net=slim.conv2d(input,channel,[1,1],rate=1,activation_fn=lrelu,normalizer_fn=nm,weights_initializer=identity_initializer(),scope='g_conv0')
    net=slim.conv2d(net,channel,[3,3],rate=1,activation_fn=lrelu,normalizer_fn=nm,weights_initializer=identity_initializer(),scope='g_conv1')
    net=slim.conv2d(net,channel,[3,3],rate=2,activation_fn=lrelu,normalizer_fn=nm,weights_initializer=identity_initializer(),scope='g_conv2')
    net=slim.conv2d(net,channel,[3,3],rate=4,activation_fn=lrelu,normalizer_fn=nm,weights_initializer=identity_initializer(),scope='g_conv3')
    net=slim.conv2d(net,channel,[3,3],rate=8,activation_fn=lrelu,normalizer_fn=nm,weights_initializer=identity_initializer(),scope='g_conv4')
    net=slim.conv2d(net,channel,[3,3],rate=16,activation_fn=lrelu,normalizer_fn=nm,weights_initializer=identity_initializer(),scope='g_conv5')
    net=slim.conv2d(net,channel,[3,3],rate=32,activation_fn=lrelu,normalizer_fn=nm,weights_initializer=identity_initializer(),scope='g_conv6')
    net=slim.conv2d(net,channel,[3,3],rate=64,activation_fn=lrelu,normalizer_fn=nm,weights_initializer=identity_initializer(),scope='g_conv7')
    net=slim.conv2d(net,channel,[3,3],rate=1,activation_fn=lrelu,normalizer_fn=nm,weights_initializer=identity_initializer(),scope='g_conv9')
    net=slim.conv2d(net,3*2,[1,1],rate=1,activation_fn=None,scope='g_conv_last') # output 6 channels --> 3 for transmission layer and 3 for reflection layer
    return net

# synthetic images
def gkern(kernlen=100, nsig=1):
    """Returns a 2D Gaussian kernel array."""
    interval = (2*nsig+1.)/(kernlen)
    x = np.linspace(-nsig-interval/2., nsig+interval/2., kernlen+1)
    kern1d = np.diff(st.norm.cdf(x))
    kernel_raw = np.sqrt(np.outer(kern1d, kern1d))
    kernel = kernel_raw/kernel_raw.sum()
    kernel = kernel/kernel.max()
    return kernel

# create a vignetting mask
g_mask=gkern(560,3)
g_mask=np.dstack((g_mask,g_mask,g_mask))

def syn_data(t,r,sigma):
    t=np.power(t,2.2)
    r=np.power(r,2.2)
    
    sz=int(2*np.ceil(2*sigma)+1)
    r_blur=cv2.GaussianBlur(r,(sz,sz),sigma,sigma,0)
    blend=r_blur+t
    
    att=1.08+np.random.random()/10.0
    
    for i in range(3):
        maski=blend[:,:,i]>1
        mean_i=max(1.,np.sum(blend[:,:,i]*maski)/(maski.sum()+1e-6))
        r_blur[:,:,i]=r_blur[:,:,i]-(mean_i-1)*att
    r_blur[r_blur>=1]=1
    r_blur[r_blur<=0]=0

    h,w=r_blur.shape[0:2]
    neww=np.random.randint(0, 560-w-10)
    newh=np.random.randint(0, 560-h-10)
    alpha1=g_mask[newh:newh+h,neww:neww+w,:]
    alpha2 = 1-np.random.random()/5.0;
    r_blur_mask=np.multiply(r_blur,alpha1)
    blend=r_blur_mask+t*alpha2
    
    t=np.power(t,1/2.2)
    r_blur_mask=np.power(r_blur_mask,1/2.2)
    blend=np.power(blend,1/2.2)
    blend[blend>=1]=1
    blend[blend<=0]=0

    return t,r_blur_mask,blend

# please follow the dataset directory setup in README
def prepare_data(train_path):
    input_names=[]
    image1=[]
    image2=[]
    for dirname in train_path:
        train_t_gt = dirname + "transmission_layer/"
        train_r_gt = dirname + "reflection_layer/"
        train_b = dirname + "blended/"
        for root, _, fnames in sorted(os.walk(train_t_gt)):
            for fname in fnames:
                if is_image_file(fname):
                    path_input = os.path.join(train_b, fname)
                    path_output1 = os.path.join(train_t_gt, fname)
                    path_output2 = os.path.join(train_r_gt, fname)
                    input_names.append(path_input)
                    image1.append(path_output1)
                    image2.append(path_output2)
    return input_names,image1,image2

_,output_names1,output_names2=prepare_data(train_syn_root) # image pairs for generating synthetic training images
input_real_names,output_real_names1,output_real_names2=prepare_data(train_real_root) # no reflection ground truth for real images
print("[i] Total %d training images, first path of real image is %s." % (len(output_names1)+len(output_real_names1), input_real_names[0]))

def compute_l1_loss(input, output):
    return tf.reduce_mean(tf.abs(input-output))

def compute_percep_loss(input, output, reuse=False):
    vgg_real=build_vgg19(output*255.0,reuse=reuse)
    vgg_fake=build_vgg19(input*255.0,reuse=True)
    p0=compute_l1_loss(vgg_real['input'],vgg_fake['input'])
    p1=compute_l1_loss(vgg_real['conv1_2'],vgg_fake['conv1_2'])/2.6
    p2=compute_l1_loss(vgg_real['conv2_2'],vgg_fake['conv2_2'])/4.8
    p3=compute_l1_loss(vgg_real['conv3_2'],vgg_fake['conv3_2'])/3.7
    p4=compute_l1_loss(vgg_real['conv4_2'],vgg_fake['conv4_2'])/5.6
    p5=compute_l1_loss(vgg_real['conv5_2'],vgg_fake['conv5_2'])*10/1.5
    return p0+p1+p2+p3+p4+p5

def compute_exclusion_loss(img1,img2,level=1):
    gradx_loss=[]
    grady_loss=[]
    
    for l in range(level):
        gradx1, grady1=compute_gradient(img1)
        gradx2, grady2=compute_gradient(img2)
        alphax=2.0*tf.reduce_mean(tf.abs(gradx1))/tf.reduce_mean(tf.abs(gradx2))
        alphay=2.0*tf.reduce_mean(tf.abs(grady1))/tf.reduce_mean(tf.abs(grady2))
        
        gradx1_s=(tf.nn.sigmoid(gradx1)*2)-1
        grady1_s=(tf.nn.sigmoid(grady1)*2)-1
        gradx2_s=(tf.nn.sigmoid(gradx2*alphax)*2)-1
        grady2_s=(tf.nn.sigmoid(grady2*alphay)*2)-1

        gradx_loss.append(tf.reduce_mean(tf.multiply(tf.square(gradx1_s),tf.square(gradx2_s)),reduction_indices=[1,2,3])**0.25)
        grady_loss.append(tf.reduce_mean(tf.multiply(tf.square(grady1_s),tf.square(grady2_s)),reduction_indices=[1,2,3])**0.25)

        img1=tf.nn.avg_pool(img1, [1,2,2,1], [1,2,2,1], padding='SAME')
        img2=tf.nn.avg_pool(img2, [1,2,2,1], [1,2,2,1], padding='SAME')
    return gradx_loss,grady_loss

def compute_gradient(img):
    gradx=img[:,1:,:,:]-img[:,:-1,:,:]
    grady=img[:,:,1:,:]-img[:,:,:-1,:]
    return gradx,grady

# set up the model
with tf.variable_scope(tf.get_variable_scope()):
    input=tf.placeholder(tf.float32,shape=[None,None,None,3])
    target=tf.placeholder(tf.float32,shape=[None,None,None,3])
    reflection=tf.placeholder(tf.float32,shape=[None,None,None,3])
    issyn=tf.placeholder(tf.bool,shape=[])

    # build the model
    network=build(input)
    transmission_layer, reflection_layer=tf.split(network, num_or_size_splits=2, axis=3)
    
    # Perceptual Loss
    loss_percep_t=compute_percep_loss(transmission_layer, target)
    loss_percep_r=tf.where(issyn, compute_percep_loss(reflection_layer, reflection, reuse=True), 0.)
    loss_percep=tf.where(issyn, loss_percep_t+loss_percep_r, loss_percep_t)
    
    # Adversarial Loss
    with tf.variable_scope("discriminator"):
        predict_real,pred_real_dict = build_discriminator(input,target)
    with tf.variable_scope("discriminator", reuse=True):
        predict_fake,pred_fake_dict = build_discriminator(input,transmission_layer)

    d_loss=(tf.reduce_mean(-(tf.log(predict_real + EPS) + tf.log(1 - predict_fake + EPS)))) * 0.5
    g_loss=tf.reduce_mean(-tf.log(predict_fake + EPS))
    
    # L1 loss on reflection image
    loss_l1_r=tf.where(issyn,compute_l1_loss(reflection_layer, reflection),0)
    
    # Gradient loss
    loss_gradx,loss_grady=compute_exclusion_loss(transmission_layer,reflection_layer,level=3)
    loss_gradxy=tf.reduce_sum(sum(loss_gradx)/3.)+tf.reduce_sum(sum(loss_grady)/3.)
    loss_grad=tf.where(issyn,loss_gradxy/2.0,0)

    loss=loss_l1_r+loss_percep*0.2+loss_grad

train_vars = tf.trainable_variables()
d_vars = [var for var in train_vars if 'discriminator' in var.name]
g_vars = [var for var in train_vars if 'g_' in var.name]
g_opt=tf.train.AdamOptimizer(learning_rate=0.0002).minimize(loss*100+g_loss, var_list=g_vars)
d_opt=tf.train.AdamOptimizer(learning_rate=0.0001).minimize(d_loss,var_list=d_vars)

for var in tf.trainable_variables():
    print(var)

saver=tf.train.Saver(max_to_keep=10)

######### Session #########
sess=tf.Session()
sess.run(tf.global_variables_initializer())
ckpt=tf.train.get_checkpoint_state(task)
print("[i] contain checkpoint: ", ckpt)
if ckpt and continue_training:
    saver_restore=tf.train.Saver([var for var in tf.trainable_variables() if 'discriminator' not in var.name])
    print('loaded '+ckpt.model_checkpoint_path)
    saver_restore.restore(sess,ckpt.model_checkpoint_path)

maxepoch=100
k_sz=np.linspace(1,5,80) # for synthetic images
num_train=len(output_names2)
g_mean=0
if is_training:
    all_l=np.zeros(num_train, dtype=float)
    all_percep=np.zeros(num_train, dtype=float)
    all_grad=np.zeros(num_train, dtype=float)
    all_g=np.zeros(num_train, dtype=float)
    for epoch in range(1,maxepoch):
        # if epoch==1 or epoch==maxepoch+1:
        input_images=[None]*num_train
        output_images_t=[None]*num_train
        output_images_r=[None]*num_train

        if os.path.isdir("%s/%04d"%(task,epoch)):
            continue
        cnt=0
        for id in np.random.permutation(num_train):
            st=time.time()
            if input_images[id] is None:
                magic=np.random.random()
                if magic < 0.7: # choose from synthetic dataset
                    is_syn=True
                    outputimg=cv2.imread(output_names1[id],-1)
                    neww=np.random.randint(256, 480)
                    newh=round((neww/outputimg.shape[1])*outputimg.shape[0])
                    output_image_t=cv2.resize(np.float32(outputimg),(neww,newh),cv2.INTER_CUBIC)/255.0
                    outputimg_r=cv2.resize(np.float32(cv2.imread(output_names2[id],-1)),(neww,newh),cv2.INTER_CUBIC)/255.0
                    file=os.path.splitext(os.path.basename(output_names1[id]))[0]
                    sigma=k_sz[np.random.randint(0, len(k_sz))]
                    if np.mean(output_image_t)*1/2 > np.mean(outputimg_r):
                        continue
                    output_image_t1,output_image_r,input_image=syn_data(output_image_t,outputimg_r,sigma)
                else: # choose from real dataste
                    is_syn=False
                    _id=id%len(input_real_names)
                    inputimg = cv2.imread(input_real_names[_id],-1)
                    file=os.path.splitext(os.path.basename(input_real_names[_id]))[0]
                    neww=np.random.randint(256, 480)
                    newh=round((neww/inputimg.shape[1])*inputimg.shape[0])
                    input_image=cv2.resize(np.float32(inputimg),(neww,newh),cv2.INTER_CUBIC)/255.0
                    output_image_t=cv2.resize(np.float32(cv2.imread(output_real_names1[_id],-1)),(neww,newh),cv2.INTER_CUBIC)/255.0
                    output_image_r=output_image_t # reflection gt not necessary
                    sigma=0.0
                input_images[id]=np.expand_dims(input_image,axis=0)
                output_images_t[id]=np.expand_dims(output_image_t,axis=0)
                output_images_r[id]=np.expand_dims(output_image_r,axis=0)
                
                # remove some degenerated images (low-light or over-saturated images), heuristically set
                if (input_images[id][:,:,0].sum() * input_images[id][:,:,1].sum() * input_images[id][:,:,2].sum()) < 1e-6:
                    print("Invalid file %s (degenerate channel)" % (file))
                    continue
                if (output_images_r[id][:,:,0].sum() * output_images_r[id][:,:,1].sum() * output_images_r[id][:,:,2].sum()) < 1e-6:
                    print("Invalid reflection file %s (degenerate channel)" % (file))
                    continue
                if input_images[id].max() < 0.2:
                    print("Invalid file %s (degenerate image)" % (file))
                    continue
                
                # alternate training, update discriminator every two iterations
                if cnt%2==0:
                    fetch_list=[d_opt]
                    # update D
                    _=sess.run(fetch_list,feed_dict={input:input_images[id],target:output_images_t[id]})
                fetch_list=[g_opt,transmission_layer,reflection_layer,
                    d_loss,g_loss,
                    loss,loss_percep,loss_grad]
                # update G
                _,output_image_t,output_image_r,current_d,current_g,current,current_percep,current_grad=\
                    sess.run(fetch_list,feed_dict={input:input_images[id],target:output_images_t[id],reflection:output_images_r[id],issyn:is_syn})
                all_l[id]=current
                all_percep[id]=current_percep
                all_grad[id]=current_grad*255
                all_g[id]=current_g
                g_mean=np.mean(all_g[np.where(all_g)])
                print("iter: %d %d || D: %.2f || G: %.2f %.2f || all: %.2f || loss: %.2f %.2f || mean: %.2f %.2f || time: %.2f"%
                    (epoch,cnt,current_d,current_g,g_mean,
                        np.mean(all_l[np.where(all_l)]),
                        current_percep,current_grad*255,
                        np.mean(all_percep[np.where(all_percep)]),np.mean(all_grad[np.where(all_grad)]),
                        time.time()-st))
                cnt+=1
                input_images[id]=1.
                output_images_t[id]=1.
                output_images_r[id]=1.