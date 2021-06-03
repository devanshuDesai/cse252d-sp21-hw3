import torch
from model import loadPretrainedWeight
from torch.autograd import Variable
import torch.optim as optim
import torch.functional as F
import dataLoader
import argparse
import torchvision.utils as vutils
from torch.utils.data import DataLoader
import model
import torch.nn as nn
import os
import numpy as np
import utils
import scipy.io as io
import warnings
warnings.filterwarnings('ignore')

parser = argparse.ArgumentParser()
# The location of training set
parser.add_argument(
    '--imageRoot', default='/datasets/cse152-252-sp20-public/hw3_data/VOCdevkit/VOC2012/JPEGImages', help='path to input images')
parser.add_argument(
    '--labelRoot', default='/datasets/cse152-252-sp20-public/hw3_data/VOCdevkit/VOC2012/SegmentationClass', help='path to input images')
parser.add_argument(
    '--fileList',
    default='/datasets/cse152-252-sp20-public/hw3_data/VOCdevkit/VOC2012/ImageSets/Segmentation/train.txt', help='path to input images')
parser.add_argument('--experiment', default='train',
                    help='the path to store sampled images and models')
parser.add_argument('--modelRoot', default='checkpoint',
                    help='the path to store the training results')
parser.add_argument('--initLR', type=float, default=0.1, help='the initial learning rate')
parser.add_argument('--nepoch', type=int, default=100, help='the training epoch')
parser.add_argument('--batchSize', type=int, default=64,
                    help='the size of a batch')
parser.add_argument('--numClasses', type=int, default=21,
                    help='the number of classes')
parser.add_argument('--isDilation', action='store_true',
                    help='whether to use dialated model or not')
parser.add_argument('--isSpp', action='store_true',
                    help='whether to do spatial pyramid or not')
parser.add_argument('--noCuda', action='store_true',
                    help='do not use cuda for training')
parser.add_argument('--gpuId', type=int, default=0,
                    help='gpu id used for training the network')
parser.add_argument('--colormap', default='colormap.mat',
                    help='colormap for visualization')

# The detail network setting
opt = parser.parse_args()
print(opt)

colormap = io.loadmat(opt.colormap)['cmap']

if opt.isSpp == True:
    opt.isDilation = False

if opt.isDilation:
    opt.experiment += '_dilation'
    opt.modelRoot += '_dilation'
if opt.isSpp:
    opt.experiment += '_spp'
    opt.modelRoot += '_spp'

# Save all the codes
os.system('mkdir %s' % opt.experiment)
os.system('cp *.py %s' % opt.experiment)

if torch.cuda.is_available() and opt.noCuda:
    print("WARNING: You have a CUDA device, so you should probably run with --cuda")

# Initialize image batch
imBatch = Variable(torch.FloatTensor(opt.batchSize, 3, 300, 300))
labelBatch = Variable(torch.FloatTensor(
    opt.batchSize, opt.numClasses, 300, 300))
maskBatch = Variable(torch.FloatTensor(opt.batchSize, 1, 300, 300))
labelIndexBatch = Variable(torch.LongTensor(opt.batchSize, 1, 300, 300))

# Initialize network
if opt.isDilation:
    encoder = model.encoderDilation()
    decoder = model.decoderDilation()
elif opt.isSpp:
    encoder = model.encoderSPP()
    decoder = model.decoderSPP()
else:
    encoder = model.encoder()
    decoder = model.decoder()

# Move network and containers to gpu
if not opt.noCuda:
    device = 'cuda'
else:
    device = 'cpu'

imBatch = imBatch.to(device)
labelBatch = labelBatch.to(device)
labelIndexBatch = labelIndexBatch.to(device)
maskBatch = maskBatch.to(device)
encoder = encoder.to(device)
decoder = decoder.to(device)

# Load pre-trained weights
loadPretrainedWeight(encoder)

# Initialize optimizer
params = list(encoder.parameters()) + list(decoder.parameters())
# optimizer = optim.RMSprop(params, lr=opt.initLR, weight_decay=1e-8, momentum=0.9)
optimizer = optim.SGD(params, lr=opt.initLR, momentum=0.9, weight_decay=5e-4)
scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, 'min', patience=2)

# Initialize dataLoader
segDataset = dataLoader.BatchLoader(
    imageRoot=opt.imageRoot,
    labelRoot=opt.labelRoot,
    fileList=opt.fileList,
    imWidth=300,
    imHeight=300
)
segLoader = DataLoader(segDataset, batch_size=opt.batchSize,
                       num_workers=4, shuffle=True)

lossArr = []
accuracyArr = []
iteration = 0
epoch = opt.nepoch
confcounts = np.zeros((opt.numClasses, opt.numClasses), dtype=np.int64)
accuracy = np.zeros(opt.numClasses, dtype=np.float32)
trainingLog = open(
    '{0}/trainingLog_{1}.txt'.format(opt.experiment, epoch), 'w')
for epoch in range(0, opt.nepoch):
    torch.cuda.manual_seed(epoch)
    trainingLog = open(
        '{0}/trainingLog_{1}.txt'.format(opt.experiment, epoch), 'w')
    for i, dataBatch in enumerate(segLoader):
        iteration += 1

        # Read data
        imBatch = Variable(dataBatch['im']).to(device)
        labelBatch = Variable(dataBatch['label']).to(device)
        labelIndexBatch = Variable(dataBatch['labelIndex']).to(device)
        maskBatch = Variable(dataBatch['mask']).to(device)

        # Train network
        optimizer.zero_grad()
        x1, x2, x3, x4, x5 = encoder(imBatch)
        pred = decoder(imBatch, x1, x2, x3, x4, x5)

        loss = torch.mean(pred * labelBatch)
        loss.backward()
        optimizer.step()

        # Compute mean IOU
        hist = utils.computeAccuracy(pred, labelIndexBatch, maskBatch)
        confcounts += hist

        for n in range(0, opt.numClasses):
            rowSum = np.sum(confcounts[n, :])
            colSum = np.sum(confcounts[:, n])
            interSum = confcounts[n, n]
            accuracy[n] = float(100.0 * interSum) / \
                max(float(rowSum + colSum - interSum), 1e-5)

        # Output the log information
        lossArr.append(loss.cpu().data.item())
        meanLoss = np.mean(np.array(lossArr[:]))
        meanAccuracy = np.mean(accuracy)
        accuracyArr.append(meanAccuracy)

        print('Epoch %d iteration %d: Loss %.5f Accumulated Loss %.5f'
              % (epoch, iteration, lossArr[-1], meanLoss))
        print('Epoch %d iteration %d: Accumulated Accuracy %.5f'
              % (epoch, iteration, meanAccuracy))
        trainingLog.write('Epoch %d iteration %d: Loss %.5f Accumulated Loss %.5f \n'
                          % (epoch, iteration, lossArr[-1], meanLoss))
        trainingLog.write('Epoch %d iteration %d: Accumulated Accuracy %.5f \n'
                          % (epoch, iteration, meanAccuracy))

        if iteration % 50 == 0:
            vutils.save_image(imBatch.data, '%s/images_%d.png' %
                              (opt.experiment, iteration), padding=0, normalize=True)
            utils.save_label(labelBatch.data, maskBatch.data, colormap,
                             '%s/labelGt_%d.png' % (opt.experiment, iteration), nrows=1, ncols=1)
            utils.save_label(-pred.data, maskBatch.data, colormap, '%s/labelPred_%d.png' %
                             (opt.experiment, iteration), nrows=1, ncols=1)

    if (epoch+1) % 2 == 0:
        np.save('%s/loss.npy' % opt.experiment, np.array(lossArr ) )
        np.save('%s/accuracy.npy' % opt.experiment, np.array(accuracyArr ) )
        torch.save(encoder.state_dict(), '%s/encoder_%d.pth' % (opt.experiment, epoch+1) )
        torch.save(decoder.state_dict(), '%s/decoder_%d.pth' % (opt.experiment, epoch+1) )

    trainingLog.close()
# Save the accuracy
# np.save('%s/accuracy_%d.npy' % (opt.experiment, opt.epochId), accuracy)
