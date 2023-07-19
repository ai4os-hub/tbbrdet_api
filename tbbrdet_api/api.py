# -*- coding: utf-8 -*-
"""
Functions to integrate your model with the DEEPaaS API.
It's usually good practice to keep this file minimal, only performing the interfacing
tasks. In this way you don't mix your true code with DEEPaaS code and everything is
more modular. That is, if you need to write the predict() function in api.py, you
would import your true predict function and call it from here (with some processing /
postprocessing in between if needed).
For example:

    import mycustomfile

    def predict(**kwargs):
        args = preprocess(kwargs)
        resp = mycustomfile.predict(args)
        resp = postprocess(resp)
        return resp

To start populating this file, take a look at the docs [1] and at a canonical exemplar
module [2].

[1]: https://docs.deep-hybrid-datacloud.eu/
[2]: https://github.com/deephdc/demo_app
"""
import logging
import os
import os.path as osp
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from tqdm import tqdm
import pkg_resources

from tbbrdet_api import configs, fields, misc
from tbbrdet_api.scripts.train import main
from tbbrdet_api.scripts.infer import infer
from tbbrdet_api.misc import (
    _catch_error, extract_zst,
    download_with_rclone, download_folder_from_nextcloud,
    check_train_from, get_pth_to_resume_from
)

logger = logging.getLogger('__name__')


@_catch_error
def get_metadata():
    """
    DO NOT REMOVE - All modules should have a get_metadata() function
    with appropriate keys.

    Returns a dictionary containing metadata information about the module.

    Returns:
        A dictionary containing metadata information required by DEEPaaS.
    """
    metadata = {
        'authors': configs.MODEL_METADATA.get("author"),
        'description': configs.MODEL_METADATA.get("summary"),
        'license': configs.MODEL_METADATA.get("license"),
        'version': configs.MODEL_METADATA.get("version"),
        'checkpoint_files_local': misc.ls_local(),
        'checkpoint_files_remote': misc.ls_remote(),
    }
    logger.debug("Package model metadata: %d", metadata)
    return metadata


def get_train_args():
    """
    Return the arguments that are needed to perform a  training.

    Returns:
        Dictionary of webargs fields.
      """
    # NOTE: potentially requires _fields_to_dict misc function for conversion!
    train_args = fields.TrainArgsSchema().fields
    logger.debug("Web arguments: %d", train_args)
    return train_args


def get_predict_args():
    """
    Return the arguments that are needed to perform a prediction.

    Args:
        None

    Returns:
        Dictionary of webargs fields.
    """
    # NOTE: potentially requires _fields_to_dict misc function for conversion!
    predict_args = fields.PredictArgsSchema().fields
    logger.debug("Web arguments: %d", predict_args)
    return predict_args


def train(**args):
    """
    Performs training on the dataset.
    Args:
        **args: keyword arguments from get_train_args.
    Returns:
        path to the trained model
    """
    # if no data in local data folder, download it from Nextcloud
    if not os.listdir(configs.DATA_PATH):
        logger.info(f"Data folder '{configs.DATA_PATH}' empty, "
                    f"downloading data from '{configs.REMOTE_DATA_DIR}'...")
        download_with_rclone(remote_folder=configs.REMOTE_DATA_DIR,
                             local_folder=configs.DATA_PATH)

        logger.info("Extracting data from any .tar.zst format files...")
        zst_paths = Path(configs.DATA_PATH).glob("**/*.tar.zst")
        for z in tqdm(zst_paths):
            extract_zst(z, Path(osp.dirname(z), "images", z.stem.split(".")[0]))

    # define specifics of training (from scratch, pretrained, resume)
    if args['ckp_resume_dir']:
        # define whether we're training from scratch or coco
        args['train_from'] = check_train_from(args['ckp_resume_dir'])

        # download model if necessary
        if "rshare" in args['ckp_resume_dir']:
            args['ckp_resume_dir'] = download_folder_from_nextcloud(
                remote_dir=args['ckp_resume_dir'],
                filetype="model", check="latest"
            )

    elif args['ckp_pretrain_pth']:
        # define that we're training from coco
        args['train_from'] = configs.settings['train_from']['coco']

        # download model if necessary
        if "rshare" in args['ckp_pretrain_pth']:
            local_pretrain_ckp_folder = download_folder_from_nextcloud(
                remote_dir=osp.dirname(args['ckp_pretrain_pth']),
                filetype="pretrained weights"
            )
            args['ckp_pretrain_pth'] = osp.join(local_pretrain_ckp_folder,
                                                osp.basename(args['ckp_pretrain_pth']))

    else:  # neither resuming nor using pretrained weights means we're training from scratch
        args['train_from'] = configs.settings['train_from']['scratch']

    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    model_dir = osp.join(configs.MODEL_DIR, args['train_from'], timestamp)
    if not osp.exists(model_dir):
        os.mkdir(model_dir)
    args['model_work_dir'] = model_dir

    main(args)

    return {f'Model and logs were saved to {args["name"]}'}


def predict(**args):
    """
    Performs inference  on an input image.
    Args:
        **args:   keyword arguments from get_predict_args.
    Returns:
        either a json file or png image with bounding box
    """
    # if the selected model is from the remote repository, download it
    if "rshare" in args['predict_model_dir']:
        args['predict_model_dir'] = download_folder_from_nextcloud(
            remote_dir=args['predict_model_dir'], filetype="model", check="best"
        )
    args['model_pth'] = get_pth_to_resume_from(directory=args['predict_model_dir'],
                                               priority=['best', 'latest', 'epoch'])
    assert args['model_pth'], f"No '.pth' files in {args['predict_model_dir']} to predict with!"

    with tempfile.TemporaryDirectory() as tmpdir:
        for f in [args['input']]:
            shutil.copy(f.filename, tmpdir + F'/{f.original_filename}')
        args['input'] = [osp.join(tmpdir, t) for t in os.listdir(tmpdir)]
        outputs, buffer = infer.main(args)

        if args['accept'] == 'image/png':
            return buffer
        else:
            return outputs


if __name__ == '__main__':
    ex_args = {
        'model': 'mask_rcnn_swin-t',
        'ckp_pretrain_pth': None,
        'ckp_resume_dir': None,
        # 'data_config': 'test_data/submarin.yaml',
        # 'use_train_aug': False,
        'device': True,
        'epochs': 1,
        'workers': 2,
        'batch': 1,
        'lr': 0.0001,
        # 'imgsz': 640,
        'seed': 42
    }
    train(**ex_args)

# def warm():
#     pass
#
#
# def get_predict_args():
#     return {}
#
#
# @_catch_error
# def predict(**kwargs):
#     return None
#
#
# def get_train_args():
#     return {}
#
#
# def train(**kwargs):
#     return None
